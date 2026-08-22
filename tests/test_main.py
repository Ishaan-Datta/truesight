import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from surya_slim import BlockOCRResult, ConfigError, FailureContext, PageOCRResult
from truesight import (
    CaptureConfig,
    check_niri_ipc,
    extract_output,
    report_ocr_failure,
)


class CaptureConfigTests(unittest.TestCase):
    def test_defaults_to_tmp(self) -> None:
        self.assertEqual(CaptureConfig().picture_directory, Path("/tmp"))

    def test_loads_capture_settings_from_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "settings.toml"
            config_path.write_text(
                """
[capture]
picture_directory = "~/screenshots"
confidence_threshold = 0.75

[endpoint_config]
api_url = "http://localhost:8000/v1"
""".strip()
            )
            config = CaptureConfig.from_toml(config_path)

        self.assertEqual(config.picture_directory, Path.home() / "screenshots")
        self.assertEqual(config.confidence_threshold, 0.75)

    def test_rejects_invalid_confidence_threshold(self) -> None:
        with self.assertRaises(ConfigError):
            CaptureConfig(confidence_threshold=1.1)


class NiriCheckTests(unittest.TestCase):
    @patch("truesight.subprocess.run")
    @patch("truesight.shutil.which", return_value="/usr/bin/niri")
    def test_checks_niri_ipc(self, _which, run) -> None:
        check_niri_ipc()

        run.assert_called_once_with(
            ["niri", "msg", "version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    @patch("truesight.shutil.which", return_value=None)
    def test_rejects_missing_niri(self, _which) -> None:
        with self.assertRaisesRegex(RuntimeError, "niri is not installed"):
            check_niri_ipc()

    @patch("truesight.shutil.which", return_value="/usr/bin/niri")
    @patch("truesight.subprocess.run")
    def test_reports_niri_ipc_failure(self, run, _which) -> None:
        run.side_effect = subprocess.CalledProcessError(
            1, ["niri", "msg", "version"], stderr="socket unavailable"
        )

        with self.assertRaisesRegex(RuntimeError, "socket unavailable"):
            check_niri_ipc()


class FailureNotificationTests(unittest.TestCase):
    @patch("truesight.print")
    @patch("truesight.subprocess.run")
    @patch("truesight.shutil.which", return_value="/usr/bin/notify-send")
    def test_notifies_user_of_ocr_failure(self, _which, run, _print) -> None:
        report_ocr_failure(
            FailureContext(
                stage="inference",
                attempts=2,
                error=RuntimeError("server disconnected"),
                api_url="http://localhost:8000/v1",
                model="surya",
            )
        )

        run.assert_called_once_with(
            [
                "notify-send",
                "Truesight OCR failed",
                "Inference failed: server disconnected",
            ],
            check=True,
            timeout=5,
        )


class OutputFilterTests(unittest.TestCase):
    @staticmethod
    def result(confidence: float | None) -> PageOCRResult:
        return PageOCRResult(
            blocks=[
                BlockOCRResult([], "Text", "Text", 0, html="first"),
                BlockOCRResult([], "Text", "Text", 1),
                BlockOCRResult([], "Text", "Text", 2, html="second"),
            ],
            image_bbox=[],
            confidence=confidence,
        )

    def test_extracts_html_at_threshold(self) -> None:
        self.assertEqual(extract_output(self.result(0.5), 0.5), "first\nsecond")

    def test_rejects_low_or_unavailable_confidence(self) -> None:
        self.assertIsNone(extract_output(self.result(0.49), 0.5))
        self.assertIsNone(extract_output(self.result(None), 0.5))


if __name__ == "__main__":
    unittest.main()
