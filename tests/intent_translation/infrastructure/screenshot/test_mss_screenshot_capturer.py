from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.intent_translation.infrastructure.screenshot.mss_screenshot_capturer import (
    MssScreenshotCapturer,
)

_MODULE = "src.intent_translation.infrastructure.screenshot.mss_screenshot_capturer.mss"


class TestCapture:
    @patch(_MODULE)
    def test_captures_configured_monitor_and_returns_png(
        self, mock_mss: MagicMock
    ) -> None:
        mock_sct = MagicMock()
        mock_sct.monitors = ["all", "monitor-1", "monitor-2"]
        shot = MagicMock(rgb=b"rgb-data", size=(100, 200))
        mock_sct.grab.return_value = shot
        mock_mss.mss.return_value.__enter__.return_value = mock_sct
        mock_mss.tools.to_png.return_value = b"png-bytes"
        capturer = MssScreenshotCapturer()

        result = capturer.capture(1)

        mock_sct.grab.assert_called_once_with("monitor-1")
        mock_mss.tools.to_png.assert_called_once_with(b"rgb-data", (100, 200))
        assert result == b"png-bytes"

    @patch(_MODULE)
    def test_monitor_index_out_of_range_returns_none(self, mock_mss: MagicMock) -> None:
        mock_sct = MagicMock()
        mock_sct.monitors = ["all", "monitor-1"]
        mock_mss.mss.return_value.__enter__.return_value = mock_sct
        capturer = MssScreenshotCapturer()

        result = capturer.capture(5)

        mock_sct.grab.assert_not_called()
        assert result is None

    @patch(_MODULE)
    def test_capture_failure_returns_none(self, mock_mss: MagicMock) -> None:
        mock_mss.mss.side_effect = RuntimeError("display not available")
        capturer = MssScreenshotCapturer()

        result = capturer.capture(1)

        assert result is None
