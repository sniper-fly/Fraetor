from __future__ import annotations

from unittest.mock import MagicMock

from src.intent_translation.application.segment_screenshot_pairer import (
    SegmentScreenshotPairer,
)
from src.shared.config.dynamic_settings import DynamicSettings


def _make_pairer(
    *, enabled: bool = True, monitor_index: int = 1
) -> tuple[SegmentScreenshotPairer, MagicMock]:
    capture = MagicMock()
    repository = MagicMock()
    repository.get.return_value = DynamicSettings(
        intent_translation_enabled=enabled, screenshot_monitor_index=monitor_index
    )
    pairer = SegmentScreenshotPairer(
        screenshot_capture=capture, settings_repository=repository
    )
    return pairer, capture


class TestOnSpeechStart:
    def test_enabled_captures_using_configured_monitor(self) -> None:
        pairer, capture = _make_pairer(enabled=True, monitor_index=2)
        capture.capture.return_value = b"png-bytes"

        pairer.on_speech_start()

        capture.capture.assert_called_once_with(2)

    def test_disabled_does_not_capture(self) -> None:
        pairer, capture = _make_pairer(enabled=False)

        pairer.on_speech_start()

        capture.capture.assert_not_called()


class TestOnFlush:
    def test_produced_text_true_queues_pending_screenshot(self) -> None:
        pairer, capture = _make_pairer()
        capture.capture.return_value = b"screenshot-1"
        pairer.on_speech_start()

        pairer.on_flush(produced_text=True)

        assert pairer.pop_ready() == b"screenshot-1"

    def test_produced_text_false_discards_pending_screenshot(self) -> None:
        """recognizedイベントが発行されないセグメントのスクリーンショットは捨てる

        (対応先のないスクリーンショットが残り続けると、以降の全セグメントの
        対応がずれるため)。
        """
        pairer, capture = _make_pairer()
        capture.capture.return_value = b"screenshot-1"
        pairer.on_speech_start()

        pairer.on_flush(produced_text=False)

        assert pairer.pop_ready() is None

    def test_fifo_order_across_multiple_segments(self) -> None:
        pairer, capture = _make_pairer()

        capture.capture.return_value = b"screenshot-a"
        pairer.on_speech_start()
        pairer.on_flush(produced_text=True)

        capture.capture.return_value = b"screenshot-b"
        pairer.on_speech_start()
        pairer.on_flush(produced_text=True)

        assert pairer.pop_ready() == b"screenshot-a"
        assert pairer.pop_ready() == b"screenshot-b"

    def test_discarded_segment_does_not_shift_subsequent_pairing(self) -> None:
        """無音のみのセグメント(produced_text=False)を挟んでも、後続の対応がずれない。"""
        pairer, capture = _make_pairer()

        capture.capture.return_value = b"screenshot-a"
        pairer.on_speech_start()
        pairer.on_flush(produced_text=True)

        capture.capture.return_value = b"silence-screenshot"
        pairer.on_speech_start()
        pairer.on_flush(produced_text=False)

        capture.capture.return_value = b"screenshot-b"
        pairer.on_speech_start()
        pairer.on_flush(produced_text=True)

        assert pairer.pop_ready() == b"screenshot-a"
        assert pairer.pop_ready() == b"screenshot-b"


class TestPopReady:
    def test_empty_queue_returns_none(self) -> None:
        pairer, _capture = _make_pairer()

        assert pairer.pop_ready() is None


class TestReset:
    def test_clears_pending_and_ready(self) -> None:
        pairer, capture = _make_pairer()
        capture.capture.return_value = b"screenshot-a"
        pairer.on_speech_start()
        pairer.on_flush(produced_text=True)

        pairer.reset()

        assert pairer.pop_ready() is None

    def test_clears_pending_before_flush(self) -> None:
        """resetがpendingも消すことを確認 (reset後のflushで残骸を積まない)。"""
        pairer, capture = _make_pairer()
        capture.capture.return_value = b"screenshot-a"
        pairer.on_speech_start()

        pairer.reset()
        pairer.on_flush(produced_text=True)

        assert pairer.pop_ready() is None
