from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock

from src.dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from src.dictation.domain.ports import SttCapabilities


def _setup_mocks(
    *, post_processing: bool = False
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """STTエンジン/VAD/AudioCaptureのモックとファクトリを返す。"""
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.stop = AsyncMock()
    mock_stt.feed_audio = MagicMock()
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing,
        post_processing=post_processing,
    )
    mock_vad = MagicMock()
    mock_audio = MagicMock()
    mock_audio.start_recording = AsyncMock()
    mock_audio.stop_recording = AsyncMock()
    return mock_stt, mock_vad, mock_audio


class TestStart:
    async def test_starts_stt_then_audio(self) -> None:
        """STT 接続 → マイクキャプチャ開始"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )

        await coordinator.start()

        mock_stt.start.assert_called_once()
        mock_audio.start_recording.assert_awaited_once_with(coordinator._on_audio_chunk)

    async def test_audio_chunk_forwarded_to_stt_and_vad(self) -> None:
        """録音コールバックのPCMチャンクがSTTとVAD両方に転送される"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )
        await coordinator.start()

        coordinator._on_audio_chunk(b"pcm-bytes")

        mock_stt.feed_audio.assert_called_once_with(b"pcm-bytes")
        mock_vad.feed.assert_called_once_with(b"pcm-bytes")

    async def test_stt_start_failure_propagates_and_leaves_no_client(self) -> None:
        """STT開始失敗時は例外を伝播し、stt_clientを残さない"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )

        with contextlib.suppress(RuntimeError):
            await coordinator.start()

        assert coordinator.stt_client is None

    async def test_audio_open_failure_stops_stt_and_propagates(self) -> None:
        """ストリームを開けない場合はSTTを停止し例外を伝播する"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_audio.start_recording = AsyncMock(
            side_effect=RuntimeError("No audio device")
        )
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )

        with contextlib.suppress(RuntimeError):
            await coordinator.start()

        mock_stt.stop.assert_called_once()
        assert coordinator.stt_client is None


class TestStop:
    async def test_stops_recording_and_stt(self) -> None:
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )
        await coordinator.start()

        await coordinator.stop()

        mock_audio.stop_recording.assert_awaited_once()
        mock_stt.stop.assert_called_once()
        assert coordinator.stt_client is None

    async def test_returns_post_processing_flag_from_capabilities(self) -> None:
        _, mock_vad, mock_audio = _setup_mocks(post_processing=True)
        mock_stt, _, _ = _setup_mocks(post_processing=True)
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )
        await coordinator.start()

        post_processing = await coordinator.stop()

        assert post_processing is True

    async def test_streaming_engine_returns_false_post_processing(self) -> None:
        mock_stt, mock_vad, mock_audio = _setup_mocks(post_processing=False)
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )
        await coordinator.start()

        post_processing = await coordinator.stop()

        assert post_processing is False


class TestLastSpeechTime:
    async def test_returns_session_start_time_before_start(self) -> None:
        _, mock_vad, mock_audio = _setup_mocks()
        mock_stt, _, _ = _setup_mocks()
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )

        assert coordinator.last_speech_time() > 0

    async def test_returns_vad_last_speech_time_after_start(self) -> None:
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_vad.last_speech_time = 12345.0
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda: mock_stt, lambda: mock_vad
        )
        await coordinator.start()

        assert coordinator.last_speech_time() == 12345.0
