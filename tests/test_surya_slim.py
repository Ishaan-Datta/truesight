import base64
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image

from surya_slim import (
    EndpointConfig,
    FailureContext,
    ModelDiscoveryError,
    OCRResponseError,
    SuryaSlimClient,
)


def completion_response(
    html: str,
    *,
    logprobs: list[float] | None = None,
) -> dict[str, object]:
    choice: dict[str, object] = {"message": {"content": html}}
    if logprobs is not None:
        choice["logprobs"] = {
            "content": [
                {"token": f"token-{index}", "logprob": value}
                for index, value in enumerate(logprobs)
            ]
        }
    return {"choices": [choice]}


class EndpointConfigTests(unittest.TestCase):
    def test_toml_overrides_lower_priority_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "settings.toml"
            config_path.write_text(
                """
[endpoint_config]
api_url = "http://toml.example/v1"
model = "toml-model"
""".strip()
            )
            config = EndpointConfig.from_toml(
                config_path,
                environ={
                    "TRUESIGHT_API_URL": "http://environment.example/v1",
                    "TRUESIGHT_MODEL": "environment-model",
                    "TRUESIGHT_API_KEY": "environment-secret",
                },
            )

        self.assertEqual(config.api_url, "http://toml.example/v1")
        self.assertEqual(config.model, "toml-model")
        self.assertEqual(config.api_key, "environment-secret")

    def test_health_url_is_derived_from_openai_api_url(self) -> None:
        config = EndpointConfig(api_url="http://localhost:8000/v1/")
        self.assertEqual(config.resolved_health_url, "http://localhost:8000/health")


class SuryaSlimClientTests(unittest.TestCase):
    def make_client(
        self,
        handler,
        **config_overrides: object,
    ) -> SuryaSlimClient:
        config_values: dict[str, object] = {
            "api_url": "http://server.test/v1",
            "health_timeout_seconds": 0.1,
            "health_interval_seconds": 0.001,
            "retry_backoff_seconds": 0.0,
        }
        config_values.update(config_overrides)
        config = EndpointConfig(**config_values)
        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http_client.close)
        return SuryaSlimClient(config, http_client=http_client)

    def test_full_page_ocr_request_parsing_and_confidence(self) -> None:
        requests: list[httpx.Request] = []
        html = """
```html
<div data-label="Code-Block" data-bbox="100 200 900 800">
  <pre data-label="Text" data-bbox="100 200 900 800"><code>x = 1</code></pre>
</div>
<div data-label="Image" data-bbox="0 0 100 100"><img alt="logo"/></div>
```
""".strip()

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/health":
                return httpx.Response(200)
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "surya-model"}]})
            if request.url.path == "/v1/chat/completions":
                return httpx.Response(
                    200,
                    json=completion_response(html, logprobs=[0.0, math.log(0.5)]),
                )
            return httpx.Response(404)

        client = self.make_client(handler)
        result = client.ocr(Image.new("RGB", (100, 50), "white"))

        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/health",
                "/v1/models",
                "/v1/chat/completions",
            ],
        )
        self.assertAlmostEqual(result.confidence, 0.75)
        self.assertEqual(result.image_bbox, [0.0, 0.0, 100.0, 50.0])
        self.assertEqual(result.blocks[0].label, "Code")
        self.assertEqual(result.blocks[0].bbox, [10.0, 10.0, 90.0, 40.0])
        self.assertNotIn("data-bbox", result.blocks[0].html)
        self.assertNotIn("data-label", result.blocks[0].html)
        self.assertFalse(hasattr(result.blocks[0], "confidence"))
        self.assertEqual(result.blocks[1].label, "Picture")
        self.assertTrue(result.blocks[1].skipped)
        self.assertEqual(result.blocks[1].html, "")

        payload = json.loads(requests[-1].content)
        self.assertEqual(payload["model"], "surya-model")
        self.assertTrue(payload["logprobs"])
        data_url = payload["messages"][0]["content"][0]["image_url"]["url"]
        encoded_png = data_url.removeprefix("data:image/png;base64,")
        with Image.open(io.BytesIO(base64.b64decode(encoded_png))) as encoded_image:
            self.assertEqual(encoded_image.width % 28, 0)
            self.assertEqual(encoded_image.height % 28, 0)

    def test_health_polling_waits_until_server_is_ready(self) -> None:
        health_requests = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal health_requests
            if request.url.path == "/health":
                health_requests += 1
                return httpx.Response(503 if health_requests == 1 else 200)
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "model"}]})
            return httpx.Response(
                200,
                json=completion_response(
                    '<div data-label="Text" data-bbox="0 0 1000 1000">ok</div>'
                ),
            )

        client = self.make_client(handler)
        client.ocr(Image.new("RGB", (100, 100)))
        self.assertEqual(health_requests, 2)

    def test_configured_model_is_used_when_discovery_fails(self) -> None:
        posted_model: str | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal posted_model
            if request.url.path == "/health":
                return httpx.Response(200)
            if request.url.path == "/v1/models":
                return httpx.Response(500)
            posted_model = json.loads(request.content)["model"]
            return httpx.Response(
                200,
                json=completion_response(
                    '<div data-label="Text" data-bbox="0 0 1000 1000">ok</div>'
                ),
            )

        client = self.make_client(handler, model="configured-model")
        client.ocr(Image.new("RGB", (100, 100)))
        self.assertEqual(posted_model, "configured-model")

    def test_model_mismatch_is_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200)
            return httpx.Response(200, json={"data": [{"id": "other-model"}]})

        client = self.make_client(handler, model="expected-model")
        with self.assertRaises(ModelDiscoveryError):
            client.ocr(Image.new("RGB", (100, 100)))

    def test_second_parse_failure_invokes_callback_then_raises(self) -> None:
        payloads: list[dict[str, object]] = []
        failures: list[FailureContext] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200)
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "model"}]})
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json=completion_response("not OCR HTML"))

        config = EndpointConfig(
            api_url="http://server.test/v1",
            retry_backoff_seconds=0,
        )
        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http_client.close)
        client = SuryaSlimClient(
            config,
            http_client=http_client,
            on_second_failure=failures.append,
        )

        with self.assertRaises(OCRResponseError):
            client.ocr(Image.new("RGB", (100, 100)))

        self.assertEqual(payloads[1]["top_p"], 0.95)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].attempts, 2)
        self.assertEqual(failures[0].stage, "parsing")


if __name__ == "__main__":
    unittest.main()
