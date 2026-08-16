import argparse
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
import time

from PIL import Image
from surya_slim import EndpointConfig, FailureContext, ocr_image

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and OCR a screenshot")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to a TOML file containing [endpoint_config]",
    )
    return parser.parse_args()


def report_ocr_failure(context: FailureContext) -> None:
    print(
        f"OCR failed after {context.attempts} attempts: {context.error}",
        file=sys.stderr,
    )


def main() -> None:
    args = parse_args()
    if shutil.which("niri") is None:
        raise RuntimeError("niri is not installed or is not available on PATH")

    config = (
        EndpointConfig.from_toml(args.config)
        if args.config is not None
        else EndpointConfig.from_environment()
    )

    out = Path.home() / "Pictures" / "Screenshots"
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC).astimezone()
    filename = out / f"screenshot-{now:%Y%m%d-%H%M%S}.png"
    filename = filename.resolve()

    # TODO: uncomment below later
    # subprocess.run(
    #     [
    #         "niri",
    #         "msg",
    #         "action",
    #         "screenshot",
    #         "--path",
    #         str(filename),
    #     ],
    #     check=True,
    # )

    filename = "/home/ishaan/Pictures/Screenshots/screenshot-20260817-100915.png"

    print(filename)

    time.sleep(2)

    started_at = perf_counter()
    with Image.open(filename) as image:
        result = ocr_image(
            image,
            config=config,
            on_second_failure=report_ocr_failure,
        )
    elapsed = perf_counter() - started_at

    confidence = (
        "unavailable" if result.confidence is None else f"{result.confidence:.3f}"
    )
    print(f"OCR completed in {elapsed:.2f}s (page confidence: {confidence})")
    for block in result.blocks:
        if block.html:
            print(block.html)


# TODO: add confidence filter
# TODO: add wlcopy for the resulting output 
# TODO: change the screenshot file to the /tmp directory

if __name__ == "__main__":
    main()
