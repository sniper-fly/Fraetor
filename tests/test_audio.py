from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audio import create_audio_capture
from src.audio_per_session import PerSessionStreamCapture
from src.audio_persistent import PersistentStreamCapture
from src.config import STT_SAMPLE_RATE


class TestCreateAudioCapture:
    def test_darwin_uses_persistent_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """macOS では CoreAudio デッドロック回避のため常駐ストリーム方式"""
        monkeypatch.setattr(sys, "platform", "darwin")
        assert isinstance(create_audio_capture(), PersistentStreamCapture)

    def test_linux_uses_per_session_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Linux では従来どおり録音中のみマイクを掴むセッション開閉方式"""
        monkeypatch.setattr(sys, "platform", "linux")
        assert isinstance(create_audio_capture(), PerSessionStreamCapture)


@patch("src.audio_base.sd")
class TestPersistentStreamCapture:
    async def test_first_start_opens_stream_with_design_spec_params(
        self, mock_sd: MagicMock
    ) -> None:
        """design.md: 16kHz, 16-bit mono PCM"""
        capture = PersistentStreamCapture()

        await capture.start_recording(MagicMock())

        mock_sd.InputStream.assert_called_once_with(
            samplerate=STT_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture._audio_callback,
        )
        mock_sd.InputStream.return_value.start.assert_called_once()

    async def test_stream_reused_across_sessions(self, mock_sd: MagicMock) -> None:
        """常駐ストリーム: セッションをまたいでもストリームを作り直さない"""
        capture = PersistentStreamCapture()
        await capture.start_recording(MagicMock())
        await capture.stop_recording()

        await capture.start_recording(MagicMock())

        mock_sd.InputStream.assert_called_once()

    async def test_stop_recording_never_stops_or_closes_stream(
        self, mock_sd: MagicMock
    ) -> None:
        """録音停止でも stop()/close() は呼ばない
        (macOS CoreAudio デッドロック回避の根幹)"""
        capture = PersistentStreamCapture()
        await capture.start_recording(MagicMock())

        await capture.stop_recording()

        mock_sd.InputStream.return_value.stop.assert_not_called()
        mock_sd.InputStream.return_value.close.assert_not_called()
        assert capture._stream is not None

    async def test_open_failure_cleans_up_and_raises(self, mock_sd: MagicMock) -> None:
        """start() 失敗時はストリームを後始末して例外を伝播する"""
        mock_sd.InputStream.return_value.start.side_effect = RuntimeError("no device")
        capture = PersistentStreamCapture()

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
        capture = PersistentStreamCapture()

        with pytest.raises(RuntimeError):
            await capture.start_recording(MagicMock())
        await capture.start_recording(MagicMock())

        assert capture._stream is not None


@patch("src.audio_base.sd")
class TestPerSessionStreamCapture:
    async def test_start_opens_stream_with_design_spec_params(
        self, mock_sd: MagicMock
    ) -> None:
        """design.md: 16kHz, 16-bit mono PCM"""
        capture = PerSessionStreamCapture()

        await capture.start_recording(MagicMock())

        mock_sd.InputStream.assert_called_once_with(
            samplerate=STT_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=capture._audio_callback,
        )
        mock_sd.InputStream.return_value.start.assert_called_once()

    async def test_stop_recording_stops_and_closes_stream(
        self, mock_sd: MagicMock
    ) -> None:
        """Linux: 録音停止でストリームを閉じてマイクを解放する"""
        capture = PerSessionStreamCapture()
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
        capture = PerSessionStreamCapture()
        await capture.start_recording(sink)

        audio_data = np.array([[7]], dtype=np.int16)

        def stop_with_inflight_callback() -> None:
            # stream.stop() 完了前にコールバックが発火するケースを模擬
            capture._audio_callback(audio_data, 1, None, MagicMock())

        mock_sd.InputStream.return_value.stop.side_effect = stop_with_inflight_callback

        await capture.stop_recording()

        sink.assert_called_once_with(audio_data.tobytes())

    async def test_each_session_opens_new_stream(self, mock_sd: MagicMock) -> None:
        capture = PerSessionStreamCapture()
        await capture.start_recording(MagicMock())
        await capture.stop_recording()

        await capture.start_recording(MagicMock())

        assert mock_sd.InputStream.call_count == 2

    async def test_stop_is_idempotent(self, mock_sd: MagicMock) -> None:
        capture = PerSessionStreamCapture()

        await capture.stop_recording()

        mock_sd.InputStream.return_value.stop.assert_not_called()

    async def test_open_failure_resets_sink_and_raises(
        self, mock_sd: MagicMock
    ) -> None:
        """開けなかった場合はシンクを残さない"""
        mock_sd.InputStream.return_value.start.side_effect = RuntimeError("no device")
        capture = PerSessionStreamCapture()

        with pytest.raises(RuntimeError, match="no device"):
            await capture.start_recording(MagicMock())

        assert capture._sink is None
        assert capture._stream is None


class TestAudioCallbackGating:
    """コールバック→シンクの書き込み制御 (audio_base 共通動作)。"""

    async def test_callback_writes_pcm_bytes_to_sink_while_recording(self) -> None:
        sink = MagicMock()
        capture = PersistentStreamCapture()
        with patch("src.audio_base.sd"):
            await capture.start_recording(sink)

        audio_data = np.array([[100], [200], [-100]], dtype=np.int16)
        capture._audio_callback(audio_data, 3, None, MagicMock())

        sink.assert_called_once_with(audio_data.tobytes())

    async def test_callback_discards_audio_when_not_recording(self) -> None:
        """録音停止中 (シンクなし) はコールバックが何も書き込まない"""
        sink = MagicMock()
        capture = PersistentStreamCapture()
        with patch("src.audio_base.sd"):
            await capture.start_recording(sink)
            await capture.stop_recording()

        audio_data = np.array([[100]], dtype=np.int16)
        capture._audio_callback(audio_data, 1, None, MagicMock())

        sink.assert_not_called()

    def test_callback_discards_audio_before_first_recording(self) -> None:
        """常駐ストリームでは録音開始前にコールバックが来ても破棄される"""
        capture = PersistentStreamCapture()

        audio_data = np.array([[100]], dtype=np.int16)
        capture._audio_callback(audio_data, 1, None, MagicMock())  # 例外にならない

    async def test_sink_swap_redirects_audio_to_new_session(self) -> None:
        """セッションをまたぐと新しいシンクにのみ書き込まれる"""
        old_sink = MagicMock()
        new_sink = MagicMock()
        capture = PersistentStreamCapture()
        with patch("src.audio_base.sd"):
            await capture.start_recording(old_sink)
            await capture.stop_recording()
            await capture.start_recording(new_sink)

        audio_data = np.array([[42]], dtype=np.int16)
        capture._audio_callback(audio_data, 1, None, MagicMock())

        old_sink.assert_not_called()
        new_sink.assert_called_once_with(audio_data.tobytes())


class TestCustomSampleRate:
    def test_custom_sample_rate(self) -> None:
        capture = PersistentStreamCapture(sample_rate=48000)
        assert capture._sample_rate == 48000
