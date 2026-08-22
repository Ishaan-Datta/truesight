import argparse
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from PIL import Image

from surya_slim import (
    ConfigError,
    EndpointConfig,
    FailureContext,
    PageOCRResult,
    ocr_image,
)


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    picture_directory: Path = Path("/tmp")
    confidence_threshold: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "picture_directory", Path(self.picture_directory).expanduser()
        )
        if (
            not isinstance(self.confidence_threshold, (int, float))
            or isinstance(self.confidence_threshold, bool)
            or not 0 <= self.confidence_threshold <= 1
        ):
            raise ConfigError("confidence_threshold must be between zero and one")

    @classmethod
    def from_toml(cls, path: str | Path) -> "CaptureConfig":
        config_path = Path(path)
        with config_path.open("rb") as config_file:
            document = tomllib.load(config_file)

        values = document.get("capture", {})
        if not isinstance(values, dict):
            raise ConfigError(f"{config_path} [capture] must be a table")

        allowed_fields = {"picture_directory", "confidence_threshold"}
        unknown_fields = set(values) - allowed_fields
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ConfigError(f"Unknown [capture] setting(s): {names}")
        return cls(**values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and OCR a screenshot")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to a TOML file containing [capture] and [endpoint_config]",
    )
    return parser.parse_args()


def require_program(program: str) -> None:
    if shutil.which(program) is None:
        raise RuntimeError(f"{program} is not installed or is not available on PATH")


def check_niri_ipc() -> None:
    require_program("niri")
    try:
        subprocess.run(
            ["niri", "msg", "version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else "unknown IPC error"
        raise RuntimeError(
            f"cannot communicate with niri over IPC: {detail}"
        ) from error


def report_ocr_failure(context: FailureContext) -> None:
    print(
        f"OCR failed after {context.attempts} attempts: {context.error}",
        file=sys.stderr,
    )


def extract_output(result: PageOCRResult, confidence_threshold: float) -> str | None:
    if result.confidence is None or result.confidence < confidence_threshold:
        return None
    return "\n".join(block.html for block in result.blocks if block.html)


def main() -> None:
    args = parse_args()
    check_niri_ipc()

    endpoint_config = (
        EndpointConfig.from_toml(args.config)
        if args.config is not None
        else EndpointConfig.from_environment()
    )
    capture_config = (
        CaptureConfig.from_toml(args.config)
        if args.config is not None
        else CaptureConfig()
    )

    out = capture_config.picture_directory
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC).astimezone()
    filename = (out / f"screenshot-{now:%Y%m%d-%H%M%S}.png").resolve()
    subprocess.run(
        [
            "niri",
            "msg",
            "action",
            "screenshot",
            "--path",
            str(filename),
        ],
        check=True,
    )

    started_at = perf_counter()
    with Image.open(filename) as image:
        result = ocr_image(
            image,
            config=endpoint_config,
            on_second_failure=report_ocr_failure,
        )
    elapsed = perf_counter() - started_at

    confidence = (
        "unavailable" if result.confidence is None else f"{result.confidence:.3f}"
    )
    print(
        f"OCR completed in {elapsed:.2f}s (page confidence: {confidence})",
        file=sys.stderr,
    )

    output = extract_output(result, capture_config.confidence_threshold)
    if output is None:
        print(
            f"OCR output rejected: confidence must be at least "
            f"{capture_config.confidence_threshold:.3f}",
            file=sys.stderr,
        )
        return

    require_program("wl-copy")
    subprocess.run(["wl-copy"], input=output, text=True, check=True)
    print(output)
