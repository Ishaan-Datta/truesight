from __future__ import annotations

import base64
import io
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Self

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from surya_slim.config import EndpointConfig
from surya_slim.models import BlockOCRResult, PageOCRResult

HIGH_ACCURACY_BBOX_PROMPT = (
    "OCR this image to HTML. Each block is a div with data-label and data-bbox "
    "(x0 y0 x1 y1, normalized 0-1000)."
)

_BBOX_SCALE = 1000
_MAX_IMAGE_SIZE = (3072, 2048)
_MIN_IMAGE_SIZE = (1792, 28)
_IMAGE_GRID_SIZE = 28

_LABELS = {
    "Caption": "Caption",
    "Footnote": "Footnote",
    "Equation-Block": "Equation",
    "List-Group": "ListGroup",
    "Page-Header": "PageHeader",
    "Page-Footer": "PageFooter",
    "Image": "Picture",
    "Section-Header": "SectionHeader",
    "Table": "Table",
    "Text": "Text",
    "Complex-Block": "Figure",
    "Code-Block": "Code",
    "Form": "Form",
    "Table-Of-Contents": "TableOfContents",
    "Figure": "Figure",
    "Chemical-Block": "ChemicalBlock",
    "Diagram": "Diagram",
    "Bibliography": "Bibliography",
    "Blank-Page": "BlankPage",
}

_SKIPPED_LABELS = {"Picture", "Figure", "Diagram", "BlankPage"}


class SuryaSlimError(RuntimeError):
    pass


class EndpointUnavailableError(SuryaSlimError):
    pass


class ModelDiscoveryError(SuryaSlimError):
    pass


class OCRResponseError(SuryaSlimError):
    pass


@dataclass(frozen=True, slots=True)
class FailureContext:
    stage: Literal["inference", "parsing"]
    attempts: int
    error: Exception
    api_url: str
    model: str | None


FailureCallback = Callable[[FailureContext], None]


@dataclass(frozen=True, slots=True)
class _Completion:
    content: str
    confidence: float | None


def _scale_to_fit(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be greater than zero")

    original_aspect_ratio = width / height
    current_pixels = width * height
    max_pixels = _MAX_IMAGE_SIZE[0] * _MAX_IMAGE_SIZE[1]
    min_pixels = _MIN_IMAGE_SIZE[0] * _MIN_IMAGE_SIZE[1]

    scale = 1.0
    if current_pixels > max_pixels:
        scale = math.sqrt(max_pixels / current_pixels)
    elif current_pixels < min_pixels:
        scale = math.sqrt(min_pixels / current_pixels)

    width_blocks = max(1, round((width * scale) / _IMAGE_GRID_SIZE))
    height_blocks = max(1, round((height * scale) / _IMAGE_GRID_SIZE))

    while width_blocks * height_blocks * _IMAGE_GRID_SIZE**2 > max_pixels:
        if width_blocks == 1 and height_blocks == 1:
            break
        if width_blocks == 1:
            height_blocks -= 1
            continue
        if height_blocks == 1:
            width_blocks -= 1
            continue

        width_loss = abs(((width_blocks - 1) / height_blocks) - original_aspect_ratio)
        height_loss = abs((width_blocks / (height_blocks - 1)) - original_aspect_ratio)
        if width_loss < height_loss:
            width_blocks -= 1
        else:
            height_blocks -= 1

    new_size = (
        width_blocks * _IMAGE_GRID_SIZE,
        height_blocks * _IMAGE_GRID_SIZE,
    )
    if new_size == image.size:
        return image
    return image.resize(new_size, resample=Image.Resampling.LANCZOS)


def _image_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _detect_repeat_loop(
    text: str,
    base_max_repeats: int = 4,
    window_size: int = 500,
    scaling_factor: float = 3.0,
) -> bool:
    if not text:
        return False
    for sequence_length in range(1, window_size // 2 + 1):
        candidate = text[-sequence_length:]
        max_repeats = int(base_max_repeats * (1 + scaling_factor / sequence_length))
        repeats = 0
        position = len(text) - sequence_length
        while (
            position >= 0 and text[position : position + sequence_length] == candidate
        ):
            repeats += 1
            position -= sequence_length
        if repeats > max_repeats:
            return True
    return False


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip()


def _mean_token_probability(logprobs: object) -> float | None:
    if not isinstance(logprobs, list):
        return None
    probabilities: list[float] = []
    for token in logprobs:
        if not isinstance(token, dict):
            continue
        log_probability = token.get("logprob")
        if isinstance(log_probability, (int, float)):
            probabilities.append(math.exp(log_probability))
    if not probabilities:
        return None
    return sum(probabilities) / len(probabilities)


def _parse_completion(response: httpx.Response) -> _Completion:
    try:
        payload = response.json()
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise OCRResponseError("Invalid OpenAI chat completion response") from error
    if not isinstance(content, str) or not content.strip():
        raise OCRResponseError("OCR server returned empty content")

    logprobs = choice.get("logprobs")
    logprob_content = logprobs.get("content") if isinstance(logprobs, dict) else None
    return _Completion(
        content=content,
        confidence=_mean_token_probability(logprob_content),
    )


def _parse_page(
    completion: _Completion,
    image_size: tuple[int, int],
) -> PageOCRResult:
    cleaned = _strip_fences(completion.content)
    soup = BeautifulSoup(cleaned, "html.parser")
    blocks: list[BlockOCRResult] = []
    width, height = image_size

    for div in soup.find_all("div", recursive=False):
        raw_label = div.get("data-label")
        raw_bbox = div.get("data-bbox")
        if not isinstance(raw_label, str) or not isinstance(raw_bbox, str):
            continue
        try:
            normalized_bbox = [float(value) for value in raw_bbox.split()]
        except ValueError:
            continue
        if len(normalized_bbox) != 4:
            continue

        for tag in div.find_all(attrs={"data-bbox": True}):
            del tag["data-bbox"]
        for tag in div.find_all(attrs={"data-label": True}):
            del tag["data-label"]

        x0, y0, x1, y1 = normalized_bbox
        polygon = [
            [x0 / _BBOX_SCALE * width, y0 / _BBOX_SCALE * height],
            [x1 / _BBOX_SCALE * width, y0 / _BBOX_SCALE * height],
            [x1 / _BBOX_SCALE * width, y1 / _BBOX_SCALE * height],
            [x0 / _BBOX_SCALE * width, y1 / _BBOX_SCALE * height],
        ]
        label = _LABELS.get(raw_label, raw_label)
        skipped = label in _SKIPPED_LABELS
        html = "" if skipped else "".join(str(child) for child in div.contents).strip()
        blocks.append(
            BlockOCRResult(
                polygon=polygon,
                label=label,
                raw_label=raw_label,
                reading_order=len(blocks),
                html=html,
                skipped=skipped,
            )
        )

    if not blocks:
        raise OCRResponseError("OCR output did not contain any valid top-level blocks")
    return PageOCRResult(
        blocks=blocks,
        image_bbox=[0.0, 0.0, float(width), float(height)],
        confidence=completion.confidence,
    )


class SuryaSlimClient:
    def __init__(
        self,
        config: EndpointConfig,
        *,
        on_second_failure: FailureCallback | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.on_second_failure = on_second_failure
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self._model: str | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        if self.config.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self.config.api_key}"}

    def _wait_until_healthy(self) -> None:
        deadline = time.monotonic() + self.config.health_timeout_seconds
        last_error: Exception | None = None
        while True:
            remaining = max(0.001, deadline - time.monotonic())
            try:
                response = self._client.get(
                    self.config.resolved_health_url,
                    headers=self._headers,
                    timeout=min(1.0, remaining),
                )
                if response.status_code == httpx.codes.OK:
                    return
                last_error = EndpointUnavailableError(
                    f"Health endpoint returned HTTP {response.status_code}"
                )
            except httpx.HTTPError as error:
                last_error = error

            if time.monotonic() >= deadline:
                raise EndpointUnavailableError(
                    f"Server did not become healthy at "
                    f"{self.config.resolved_health_url} within "
                    f"{self.config.health_timeout_seconds} seconds"
                ) from last_error
            time.sleep(min(self.config.health_interval_seconds, remaining))

    def _discover_model(self) -> str:
        models_url = f"{self.config.api_url}/models"
        try:
            response = self._client.get(
                models_url,
                headers=self._headers,
                timeout=min(5.0, self.config.request_timeout_seconds),
            )
            response.raise_for_status()
            payload = response.json()
            model_entries = payload.get("data", [])
            model_ids = [
                entry["id"]
                for entry in model_entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            ]
        except (httpx.HTTPError, ValueError, AttributeError) as error:
            if self.config.model is not None:
                return self.config.model
            raise ModelDiscoveryError(
                f"Could not discover a model from {models_url}"
            ) from error

        if self.config.model is not None:
            if model_ids and self.config.model not in model_ids:
                available = ", ".join(model_ids)
                raise ModelDiscoveryError(
                    f"Configured model {self.config.model!r} is not served by "
                    f"{self.config.api_url}; available models: {available}"
                )
            return self.config.model
        if not model_ids:
            raise ModelDiscoveryError(f"No models were reported by {models_url}")
        return model_ids[0]

    def _ensure_ready(self) -> str:
        if self._model is None:
            self._wait_until_healthy()
            self._model = self._discover_model()
        return self._model

    def _request(
        self,
        data_url: str,
        model: str,
        *,
        retry: bool,
        generation_failure: bool,
    ) -> _Completion:
        temperature = self.config.temperature
        top_p = self.config.top_p
        if retry:
            temperature = min(temperature + 0.2, 0.8)
            if generation_failure:
                top_p = 0.95

        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": HIGH_ACCURACY_BBOX_PROMPT},
                    ],
                }
            ],
            "max_tokens": self.config.max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        payload["logprobs"] = True

        response = self._client.post(
            f"{self.config.api_url}/chat/completions",
            headers=self._headers,
            json=payload,
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        completion = _parse_completion(response)
        if _detect_repeat_loop(completion.content):
            raise OCRResponseError("OCR output ended in a repetition loop")
        return completion

    def _notify_second_failure(
        self,
        error: Exception,
        *,
        model: str,
    ) -> None:
        if self.on_second_failure is None:
            return
        stage: Literal["inference", "parsing"] = (
            "parsing" if isinstance(error, OCRResponseError) else "inference"
        )
        context = FailureContext(
            stage=stage,
            attempts=2,
            error=error,
            api_url=self.config.api_url,
            model=model,
        )
        try:
            self.on_second_failure(context)
        except Exception as callback_error:  # noqa: BLE001
            error.add_note(f"on_second_failure also failed: {callback_error!r}")

    def ocr(self, image: Image.Image) -> PageOCRResult:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a PIL.Image.Image")

        original_size = image.size
        resized_image = _scale_to_fit(image)
        data_url = _image_data_url(resized_image)
        model = self._ensure_ready()

        first_error: Exception | None = None
        for attempt in range(2):
            try:
                completion = self._request(
                    data_url,
                    model,
                    retry=attempt == 1,
                    generation_failure=isinstance(first_error, OCRResponseError),
                )
                return _parse_page(completion, original_size)
            except (httpx.HTTPError, OCRResponseError) as error:
                if attempt == 0:
                    first_error = error
                    if not isinstance(error, OCRResponseError):
                        time.sleep(self.config.retry_backoff_seconds)
                    continue
                self._notify_second_failure(error, model=model)
                raise

        raise AssertionError("unreachable")


def ocr_image(
    image: Image.Image,
    *,
    config: EndpointConfig,
    on_second_failure: FailureCallback | None = None,
) -> PageOCRResult:
    with SuryaSlimClient(
        config,
        on_second_failure=on_second_failure,
    ) as client:
        return client.ocr(image)
