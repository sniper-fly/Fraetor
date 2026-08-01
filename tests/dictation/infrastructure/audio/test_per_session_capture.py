from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.dictation.infrastructure.audio.per_session_capture import (
    PerSessionStreamCapture,
)

_SAMPLE_RATE = 16000


@patch("src.dictation.infrastructure.audio.sounddevice_base.sd")
class TestPerSessionStreamCapture:
    async def test_start_opens_stream_with_design_spec_params(
        self, mock_sd: MagicMock
    ) -> None:
        """design.md: 16kHz, 16-bit mono PCM"""
        capture = PerSessionStreamCapture(_SAMPLE_RATE)

        await capture.start_recording(MagicMock())

        mock_sd.InputStream.assert_called_once_with(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture._audio_callback,
        )
        mock_sd.InputStream.return_value.start.assert_called_once()

    async def test_stop_recording_stops_and_closes_stream(
        self, mock_sd: MagicMock
    ) -> None:
        """Linux: 録音停止でストリームを閉じてマイクを解放する"""
        capture = PerSessionStreamCapture(_SAMPLE_RATE)
        await capture.start_recording(MagicMock())

        await capture.stop_recording()

        mock_sd.InputStream.return_value.stop.assert_called_once()
        mock_sd.InputStream.return_value.close.assert_called_once()
        assert capture._stream is None
        assert capture._sink is None

    async def test_trailing_frames_during_stop_reach_sink(
        self, mock_sd: MagicMock
    ) -> None:
        """停止処理が完了するまでに届いた末尾フレームは破棄せずシンクに書き込む
        (ストリーム停止後にシンクを外す順序の保証)"""
        sink = MagicMock()
        capture = PerSessionStreamCapture(_SAMPLE_RATE)
        await capture.start_recording(sink)

        audio_data = np.array([[7]], dtype=np.int16)

        def stop_with_inflight_callback() -> None:
            # stream.stop() 完了前にコールバックが発火するケースを模擬
            capture._audio_callback(audio_data, 1, None, MagicMock())

        mock_sd.InputStream.return_value.stop.side_effect = stop_with_inflight_callback

        await capture.stop_recording()

        sink.assert_called_once_with(audio_data.tobytes())

    async def test_each_session_opens_new_stream(self, mock_sd: MagicMock) -> None:
        capture = PerSessionStreamCapture(_SAMPLE_RATE)
        await capture.start_recording(MagicMock())
        await capture.stop_recording()

        await capture.start_recording(MagicMock())

        assert mock_sd.InputStream.call_count == 2

    async def test_stop_is_idempotent(self, mock_sd: MagicMock) -> None:
        capture = PerSessionStreamCapture(_SAMPLE_RATE)

        await capture.stop_recording()

        mock_sd.InputStream.return_value.stop.assert_not_called()

    async def test_open_failure_resets_sink_and_raises(
        self, mock_sd: MagicMock
    ) -> None:
        """開けなかった場合はシンクを残さない"""
        mock_sd.InputStream.return_value.start.side_effect = RuntimeError("no device")
        capture = PerSessionStreamCapture(_SAMPLE_RATE)

        with pytest.raises(RuntimeError, match="no device"):
            await capture.start_recording(MagicMock())

        assert capture._sink is None
        assert capture._stream is None
