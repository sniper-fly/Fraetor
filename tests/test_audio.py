from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from src.audio import AudioCapture
from src.config import STT_SAMPLE_RATE


class TestAudioCapture:
    @patch("src.audio.sd")
    def test_start_creates_stream_with_design_spec_params(
        self, mock_sd: MagicMock
    ) -> None:
        """design.md: 16kHz, 16-bit mono PCM"""
        sink = MagicMock()
        capture = AudioCapture(write_audio=sink)

        capture.start()

        mock_sd.InputStream.assert_called_once_with(
            samplerate=STT_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture._audio_callback,
        )
        mock_sd.InputStream.return_value.start.assert_called_once()

    @patch("src.audio.sd")
    def test_stop_closes_stream(self, mock_sd: MagicMock) -> None:
        sink = MagicMock()
        capture = AudioCapture(write_audio=sink)
        capture.start()

        capture.stop()

        mock_sd.InputStream.return_value.stop.assert_called_once()
        mock_sd.InputStream.return_value.close.assert_called_once()
        assert capture._stream is None

    @patch("src.audio.sd")
    def test_stop_is_idempotent(self, mock_sd: MagicMock) -> None:
        sink = MagicMock()
        capture = AudioCapture(write_audio=sink)
        capture.stop()
        mock_sd.InputStream.return_value.stop.assert_not_called()

    def test_callback_writes_pcm_bytes_to_sink(self) -> None:
        sink = MagicMock()
        capture = AudioCapture(write_audio=sink)

        audio_data = np.array([[100], [200], [-100]], dtype=np.int16)
        capture._audio_callback(audio_data, 3, None, MagicMock())

        sink.assert_called_once_with(audio_data.tobytes())

    def test_custom_sample_rate(self) -> None:
        """write_audio に渡すデータは sample_rate に依存しない (バイト変換のみ)"""
        sink = MagicMock()
        capture = AudioCapture(write_audio=sink, sample_rate=48000)
        assert capture._sample_rate == 48000
