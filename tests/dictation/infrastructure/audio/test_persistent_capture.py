from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.dictation.infrastructure.audio.persistent_capture import (
    PersistentStreamCapture,
)

_SAMPLE_RATE = 16000


@patch("src.dictation.infrastructure.audio.sounddevice_base.sd")
class TestPersistentStreamCapture:
    async def test_first_start_opens_stream_with_design_spec_params(
        self, mock_sd: MagicMock
    ) -> None:
        """design.md: 16kHz, 16-bit mono PCM"""
        capture = PersistentStreamCapture(_SAMPLE_RATE)

        await capture.start_recording(MagicMock())

        mock_sd.InputStream.assert_called_once_with(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture._audio_callback,
        )
        mock_sd.InputStream.return_value.start.assert_called_once()

    async def test_stream_reused_across_sessions(self, mock_sd: MagicMock) -> None:
        """常駐ストリーム: セッションをまたいでもストリームを作り直さない"""
        capture = PersistentStreamCapture(_SAMPLE_RATE)
        await capture.start_recording(MagicMock())
        await capture.stop_recording()

        await capture.start_recording(MagicMock())

        mock_sd.InputStream.assert_called_once()

    async def test_stop_recording_never_stops_or_closes_stream(
        self, mock_sd: MagicMock
    ) -> None:
        """録音停止でも stop()/close() は呼ばない
        (macOS CoreAudio デッドロック回避の根幹)"""
        capture = PersistentStreamCapture(_SAMPLE_RATE)
        await capture.start_recording(MagicMock())

        await capture.stop_recording()

        mock_sd.InputStream.return_value.stop.assert_not_called()
        mock_sd.InputStream.return_value.close.assert_not_called()
        assert capture._stream is not None

    async def test_open_failure_cleans_up_and_raises(self, mock_sd: MagicMock) -> None:
        """start() 失敗時はストリームを後始末して例外を伝播する"""
        mock_sd.InputStream.return_value.start.side_effect = RuntimeError("no device")
        capture = PersistentStreamCapture(_SAMPLE_RATE)

        with pytest.raises(RuntimeError, match="no device"):
            await capture.start_recording(MagicMock())

        mock_sd.InputStream.return_value.close.assert_called_once()
        assert capture._stream is None

    async def test_can_retry_after_open_failure(self, mock_sd: MagicMock) -> None:
        """開きそこねた場合、次の start_recording で再試行できる"""
        mock_sd.InputStream.return_value.start.side_effect = [
            RuntimeError("no device"),
            None,
        ]
        capture = PersistentStreamCapture(_SAMPLE_RATE)

        with pytest.raises(RuntimeError):
            await capture.start_recording(MagicMock())
        await capture.start_recording(MagicMock())

        assert capture._stream is not None
