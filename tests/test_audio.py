from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audio import AudioCapture
from src.config import STT_SAMPLE_RATE


class TestEnsureOpen:
    @patch("src.audio.sd")
    async def test_opens_stream_with_design_spec_params(
        self, mock_sd: MagicMock
    ) -> None:
        """design.md: 16kHz, 16-bit mono PCM"""
        capture = AudioCapture()

        await capture.ensure_open()

        mock_sd.InputStream.assert_called_once_with(
            samplerate=STT_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture._audio_callback,
        )
        mock_sd.InputStream.return_value.start.assert_called_once()

    @patch("src.audio.sd")
    async def test_second_call_does_not_reopen(self, mock_sd: MagicMock) -> None:
        """常駐ストリーム: 2回目以降の ensure_open はストリームを作り直さない"""
        capture = AudioCapture()
        await capture.ensure_open()

        await capture.ensure_open()

        mock_sd.InputStream.assert_called_once()

    @patch("src.audio.sd")
    async def test_start_failure_closes_stream_and_raises(
        self, mock_sd: MagicMock
    ) -> None:
        """start() 失敗時はストリームを後始末して例外を伝播する"""
        mock_sd.InputStream.return_value.start.side_effect = RuntimeError("no device")
        capture = AudioCapture()

        with pytest.raises(RuntimeError, match="no device"):
            await capture.ensure_open()

        mock_sd.InputStream.return_value.close.assert_called_once()
        assert capture._stream is None

    @patch("src.audio.sd")
    async def test_can_retry_after_open_failure(self, mock_sd: MagicMock) -> None:
        """開きそこねた場合、次の ensure_open で再試行できる"""
        mock_sd.InputStream.return_value.start.side_effect = [
            RuntimeError("no device"),
            None,
        ]
        capture = AudioCapture()

        with pytest.raises(RuntimeError):
            await capture.ensure_open()
        await capture.ensure_open()

        assert capture._stream is not None


class TestRecordingGate:
    def test_callback_writes_pcm_bytes_to_sink_while_recording(self) -> None:
        sink = MagicMock()
        capture = AudioCapture()
        capture.start_recording(sink)

        audio_data = np.array([[100], [200], [-100]], dtype=np.int16)
        capture._audio_callback(audio_data, 3, None, MagicMock())

        sink.assert_called_once_with(audio_data.tobytes())

    def test_callback_discards_audio_when_not_recording(self) -> None:
        """録音停止中 (シンクなし) はコールバックが何も書き込まない"""
        sink = MagicMock()
        capture = AudioCapture()
        capture.start_recording(sink)
        capture.stop_recording()

        audio_data = np.array([[100]], dtype=np.int16)
        capture._audio_callback(audio_data, 1, None, MagicMock())

        sink.assert_not_called()

    def test_callback_discards_audio_before_first_recording(self) -> None:
        """ストリームは常駐するため、録音開始前のコールバックは破棄される"""
        capture = AudioCapture()

        audio_data = np.array([[100]], dtype=np.int16)
        capture._audio_callback(audio_data, 1, None, MagicMock())  # 例外にならない

    @patch("src.audio.sd")
    async def test_stop_recording_keeps_stream_open(self, mock_sd: MagicMock) -> None:
        """録音停止してもストリームの stop()/close() は呼ばない
        (macOS CoreAudio デッドロック回避の根幹)"""
        capture = AudioCapture()
        await capture.ensure_open()
        capture.start_recording(MagicMock())

        capture.stop_recording()

        mock_sd.InputStream.return_value.stop.assert_not_called()
        mock_sd.InputStream.return_value.close.assert_not_called()
        assert capture._stream is not None

    def test_sink_swap_redirects_audio_to_new_session(self) -> None:
        """セッションをまたぐと新しいシンクにのみ書き込まれる"""
        old_sink = MagicMock()
        new_sink = MagicMock()
        capture = AudioCapture()
        capture.start_recording(old_sink)
        capture.stop_recording()
        capture.start_recording(new_sink)

        audio_data = np.array([[42]], dtype=np.int16)
        capture._audio_callback(audio_data, 1, None, MagicMock())

        old_sink.assert_not_called()
        new_sink.assert_called_once_with(audio_data.tobytes())


class TestCustomSampleRate:
    def test_custom_sample_rate(self) -> None:
        capture = AudioCapture(sample_rate=48000)
        assert capture._sample_rate == 48000
