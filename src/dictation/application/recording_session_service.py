from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from src.dictation.application.session_timeout_monitor import SessionTimeoutMonitor
from src.dictation.domain.models import RecordingSession, TranscriptionJob

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState
    from src.dictation.application.audio_pipeline_coordinator import (
        AudioPipelineCoordinator,
    )
    from src.dictation.application.stt_event_relay import SttEventRelay
    from src.dictation.application.transcription_queue import TranscriptionQueue

logger = logging.getLogger(__name__)


class RecordingSessionService:
    """録音 (マイク) のライフサイクルを管理する最上位Facade。

    `AudioPipelineCoordinator` (STT/VAD制御) と `SttEventRelay` (リアルタイム
    イベント処理) を組み立て、`SessionTimeoutMonitor` によるタイムアウト自動
    停止を仕込む。文字起こし本体 (STT の stop() 呼び出し) は `stop_session()`
    内では実行せず、`TranscriptionQueue` にジョブとして委譲して即座に返る。
    これにより文字起こし処理中でも次の `start_session()` をすぐに開始できる。
    """

    def __init__(
        self,
        app_state: AppState,
        audio_pipeline: AudioPipelineCoordinator,
        event_relay: SttEventRelay,
        transcription_queue: TranscriptionQueue,
        *,
        max_session_duration_sec: float,
        silence_timeout_sec: float,
    ) -> None:
        self._app_state = app_state
        self._audio_pipeline = audio_pipeline
        self._event_relay = event_relay
        self._transcription_queue = transcription_queue
        self._max_session_duration_sec = max_session_duration_sec
        self._silence_timeout_sec = silence_timeout_sec
        self._lock = asyncio.Lock()
        self._timeout_monitor: SessionTimeoutMonitor | None = None

    async def start_session(self) -> None:
        """セッションを開始し、録音を開始する。"""
        async with self._lock:
            if self._app_state.recording:
                return

            session = RecordingSession(
                id=str(uuid4()),
                segments=[],
                started_at=datetime.now(tz=UTC),
            )
            self._app_state.current_session = session
            self._app_state.recording = True

            try:
                await self._audio_pipeline.start()
            except Exception:
                logger.exception("Session start failed")
                await self._abort_session_start()
                return

            event_queue = self._audio_pipeline.event_queue
            if event_queue is None:
                msg = "audio_pipeline.start() succeeded but event_queue is None"
                raise RuntimeError(msg)
            self._event_relay.start(event_queue)
            self._timeout_monitor = SessionTimeoutMonitor(
                max_duration_sec=self._max_session_duration_sec,
                silence_timeout_sec=self._silence_timeout_sec,
                last_speech_time_fn=self._audio_pipeline.last_speech_time,
                on_timeout=self._on_timeout,
            )
            self._timeout_monitor.start()

            await self._app_state.broadcaster.broadcast(
                "status", {"recording": True, "session_id": session.id}
            )
            logger.info("Session started: %s", session.id)

    async def _abort_session_start(self) -> None:
        """セッション開始に失敗した場合のクリーンアップ。"""
        self._app_state.current_session = None
        self._app_state.recording = False
        await self._app_state.broadcaster.broadcast(
            "error", {"message": "セッション開始に失敗しました。"}
        )

    async def stop_session(self, *, timed_out: bool = False) -> None:
        """録音を停止し、文字起こしジョブをキューに投入する。

        文字起こし完了 (STTの `stop()`) を待たずに即座に返る。処理完了後の
        `session_end` 配信や `pending_session` 更新は `TranscriptionQueue`
        が担う。
        """
        async with self._lock:
            if not self._app_state.recording:
                return

            self._app_state.recording = False

            if self._timeout_monitor:
                await self._timeout_monitor.stop()
                self._timeout_monitor = None

            await self._event_relay.stop()

            stopped = await self._audio_pipeline.stop()

            recording_session = self._app_state.current_session
            self._app_state.current_session = None

            if stopped is not None and recording_session is not None:
                stt_client, event_queue = stopped
                await self._transcription_queue.enqueue(
                    TranscriptionJob(
                        session=recording_session,
                        stt_client=stt_client,
                        event_queue=event_queue,
                        timed_out=timed_out,
                    )
                )

            await self._app_state.broadcaster.broadcast("status", {"recording": False})

            if recording_session:
                logger.info(
                    "Session stopped: %s (timed_out=%s)",
                    recording_session.id,
                    timed_out,
                )

    async def _on_timeout(self) -> None:
        await self.stop_session(timed_out=True)
