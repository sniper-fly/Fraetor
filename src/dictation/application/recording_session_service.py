from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from src.dictation.application.session_timeout_monitor import SessionTimeoutMonitor
from src.dictation.domain.models import RecordingSession
from src.transcript_history.domain.models import FinalizedSession

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState
    from src.dictation.application.audio_pipeline_coordinator import (
        AudioPipelineCoordinator,
    )
    from src.dictation.application.stt_event_relay import SttEventRelay

logger = logging.getLogger(__name__)


class RecordingSessionService:
    """セッションのライフサイクルを管理する最上位Facade。

    `AudioPipelineCoordinator` (STT/VAD制御) と `SttEventRelay` (イベント処理)
    を組み立て、`SessionTimeoutMonitor` によるタイムアウト自動停止を仕込む。
    """

    def __init__(
        self,
        app_state: AppState,
        audio_pipeline: AudioPipelineCoordinator,
        event_relay: SttEventRelay,
        *,
        max_session_duration_sec: float,
        silence_timeout_sec: float,
    ) -> None:
        self._app_state = app_state
        self._audio_pipeline = audio_pipeline
        self._event_relay = event_relay
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
            self._event_relay.reset()

            try:
                await self._audio_pipeline.start()
            except Exception:
                logger.exception("Session start failed")
                await self._abort_session_start()
                return

            self._event_relay.start()
            self._timeout_monitor = SessionTimeoutMonitor(
                max_duration_sec=self._max_session_duration_sec,
                silence_timeout_sec=self._silence_timeout_sec,
                last_speech_time_fn=self._audio_pipeline.last_speech_time,
                on_timeout=self._on_timeout,
            )
            self._timeout_monitor.start()

            await self._app_state.broadcaster.broadcast("status", {"recording": True})
            logger.info("Session started: %s", session.id)

    async def _abort_session_start(self) -> None:
        """セッション開始に失敗した場合のクリーンアップ。"""
        self._app_state.current_session = None
        self._app_state.recording = False
        await self._app_state.broadcaster.broadcast(
            "error", {"message": "セッション開始に失敗しました。"}
        )

    async def stop_session(self, *, timed_out: bool = False) -> FinalizedSession | None:
        """セッションを停止し、確定済みセッションを返す。"""
        async with self._lock:
            if not self._app_state.recording:
                return None

            self._app_state.recording = False

            if self._timeout_monitor:
                await self._timeout_monitor.stop()
                self._timeout_monitor = None

            post_processing = await self._audio_pipeline.stop()

            if post_processing:
                await self._app_state.broadcaster.broadcast(
                    "processing", {"message": "文字起こし中..."}
                )

            await self._event_relay.stop_and_drain()

            if post_processing:
                await self._app_state.broadcaster.broadcast("processing_done", {})

            recording_session = self._app_state.current_session
            finalized: FinalizedSession | None = None
            if recording_session:
                finalized = FinalizedSession.from_recording(
                    recording_session,
                    ended_at=datetime.now(tz=UTC),
                    timed_out=timed_out,
                )
                self._app_state.pending_session = finalized

            self._app_state.current_session = None

            await self._app_state.broadcaster.broadcast("session_end", {})
            await self._app_state.broadcaster.broadcast("status", {"recording": False})

            if finalized:
                logger.info(
                    "Session ended: %s (timed_out=%s, segments=%d)",
                    finalized.id,
                    timed_out,
                    len(finalized.segments),
                )

            return finalized

    async def _on_timeout(self) -> None:
        await self.stop_session(timed_out=True)
