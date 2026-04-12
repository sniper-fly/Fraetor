from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from src.audio import AudioCapture
from src.clipboard import copy_and_paste
from src.config import MAX_SESSION_DURATION_SEC
from src.history import save_session
from src.models import Segment, Session
from src.stt import AzureSttClient

if TYPE_CHECKING:
    from src.state import AppState

logger = logging.getLogger(__name__)


class SessionManager:
    """セッションのライフサイクルを管理する。

    録音開始時に AudioCapture + AzureSttClient を起動し、
    STTイベントをセグメントに変換してSSEでブラウザに配信する。
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._stt_client: AzureSttClient | None = None
        self._audio_capture: AudioCapture | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._next_segment_id: int = 0

    async def start_session(self) -> None:
        """セッションを開始し、録音を開始する。"""
        if self._app_state.recording:
            return

        session = Session(
            id=str(uuid4()),
            segments=[],
            started_at=datetime.now(tz=UTC),
            paste_enabled=self._app_state.paste_enabled,
        )
        self._app_state.current_session = session
        self._app_state.recording = True
        self._next_segment_id = 0

        try:
            self._stt_client = AzureSttClient(self._app_state.stt_event_queue)
            await self._stt_client.start()
        except Exception:
            logger.exception("Azure STT start failed")
            await self._abort_session_start()
            return

        try:
            self._audio_capture = AudioCapture(self._stt_client.write_audio)
            self._audio_capture.start()
        except Exception:
            logger.exception("Audio capture start failed")
            await self._abort_session_start()
            return

        self._event_task = asyncio.create_task(self._process_stt_events())
        self._timeout_task = asyncio.create_task(self._session_timeout())

        await self._app_state.broadcaster.broadcast("status", {"recording": True})
        logger.info("Session started: %s", session.id)

    async def _abort_session_start(self) -> None:
        """セッション開始に失敗した場合のクリーンアップ。"""
        if self._audio_capture:
            self._audio_capture.stop()
            self._audio_capture = None
        if self._stt_client:
            try:
                await self._stt_client.stop()
            except Exception:
                logger.exception("Failed to stop STT during abort")
            self._stt_client = None
        self._app_state.current_session = None
        self._app_state.recording = False
        await self._app_state.broadcaster.broadcast(
            "error", {"message": "セッション開始に失敗しました。"}
        )

    async def stop_session(self, *, timed_out: bool = False) -> Session | None:
        """セッションを停止し、最終テキストを組み立てて返す。"""
        if not self._app_state.recording:
            return None

        self._app_state.recording = False

        if self._audio_capture:
            self._audio_capture.stop()
            self._audio_capture = None

        if self._stt_client:
            await self._stt_client.stop()
            self._stt_client = None

        if self._event_task:
            self._event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_task
            self._event_task = None

        if self._timeout_task and self._timeout_task is not asyncio.current_task():
            self._timeout_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._timeout_task
        self._timeout_task = None

        # 残りの recognized イベントを処理
        await self._drain_stt_queue()

        session = self._app_state.current_session
        session_end_data: dict[str, object] = {}
        if session:
            session.ended_at = datetime.now(tz=UTC)
            session.timed_out = timed_out
            if session.paste_enabled and session.full_text:
                try:
                    await copy_and_paste(session.full_text)
                except Exception:
                    logger.exception("Failed to copy and paste session text")
            elif not session.paste_enabled:
                self._app_state.pending_session = session
                session_end_data["paste_enabled"] = False

        self._app_state.current_session = None

        await self._app_state.broadcaster.broadcast("session_end", session_end_data)
        await self._app_state.broadcaster.broadcast("status", {"recording": False})

        if session:
            if session.paste_enabled:
                try:
                    save_session(session)
                except Exception:
                    logger.exception("Failed to save session history")
            logger.info(
                "Session ended: %s (timed_out=%s, segments=%d, paste_enabled=%s)",
                session.id,
                timed_out,
                len(session.segments),
                session.paste_enabled,
            )

        return session

    async def _process_stt_events(self) -> None:
        """STTイベントキューを監視し、セグメント作成+SSEブロードキャストを行う。"""
        try:
            while True:
                event = await self._app_state.stt_event_queue.get()
                if event["type"] == "interim":
                    await self._app_state.broadcaster.broadcast(
                        "interim", {"text": event["text"]}
                    )
                elif event["type"] == "recognized":
                    segment = self._add_segment(event["text"])
                    await self._app_state.broadcaster.broadcast(
                        "recognized",
                        {"segment_id": segment.id, "text": segment.text},
                    )
        except asyncio.CancelledError:
            pass

    async def _drain_stt_queue(self) -> None:
        """停止後にキューに残った recognized イベントをセグメントに反映する。"""
        while not self._app_state.stt_event_queue.empty():
            try:
                event = self._app_state.stt_event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if event["type"] != "recognized":
                continue
            segment = self._add_segment(event["text"])
            await self._app_state.broadcaster.broadcast(
                "recognized",
                {"segment_id": segment.id, "text": segment.text},
            )

    def _add_segment(self, text: str) -> Segment:
        """認識済みテキストからセグメントを作成し、セッションに追加する。"""
        segment = Segment(
            id=self._next_segment_id,
            text=text,
        )
        self._next_segment_id += 1
        if self._app_state.current_session:
            self._app_state.current_session.segments.append(segment)
        return segment

    async def _session_timeout(self) -> None:
        """MAX_SESSION_DURATION_SEC 後にセッションを自動停止する。"""
        await asyncio.sleep(MAX_SESSION_DURATION_SEC)
        logger.info("Session timed out after %d seconds", MAX_SESSION_DURATION_SEC)
        await self.stop_session(timed_out=True)
