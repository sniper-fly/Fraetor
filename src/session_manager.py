from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from src.config import MAX_SESSION_DURATION_SEC, SILENCE_TIMEOUT_SEC
from src.models import Segment, Session
from src.stt_mai import MaiTranscribeClient
from src.vad import SpeechActivityDetector

if TYPE_CHECKING:
    from src.audio_base import AudioCapture
    from src.state import AppState
    from src.stt_base import SttEngine

logger = logging.getLogger(__name__)


class SessionManager:
    """セッションのライフサイクルを管理する。

    録音開始時に AudioCapture + STT エンジンを起動し、
    STTイベントをセグメントに変換してSSEでブラウザに配信する。
    """

    def __init__(self, app_state: AppState, audio_capture: AudioCapture) -> None:
        self._app_state = app_state
        self._audio_capture = audio_capture
        self._lock = asyncio.Lock()
        self._stt_client: SttEngine | None = None
        self._vad: SpeechActivityDetector | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._next_segment_id: int = 0

    async def start_session(self) -> None:
        """セッションを開始し、録音を開始する。"""
        async with self._lock:
            if self._app_state.recording:
                return

            session = Session(
                id=str(uuid4()),
                segments=[],
                started_at=datetime.now(tz=UTC),
            )
            self._app_state.current_session = session
            self._app_state.recording = True
            self._next_segment_id = 0

            try:
                self._stt_client = MaiTranscribeClient(self._app_state.stt_event_queue)
                await self._stt_client.start()
            except Exception:
                logger.exception("STT start failed")
                await self._abort_session_start()
                return

            self._vad = SpeechActivityDetector()

            try:
                await self._audio_capture.start_recording(self._on_audio_chunk)
            except Exception:
                logger.exception("Audio capture start failed")
                await self._abort_session_start()
                return

            self._event_task = asyncio.create_task(self._process_stt_events())
            self._timeout_task = asyncio.create_task(self._session_timeout())

            await self._app_state.broadcaster.broadcast("status", {"recording": True})
            logger.info("Session started: %s", session.id)

    def _on_audio_chunk(self, buffer: bytes) -> None:
        """PCMチャンクをSTTとVADの両方に転送する。"""
        if self._stt_client:
            self._stt_client.feed_audio(buffer)
        if self._vad:
            self._vad.feed(buffer)

    async def _abort_session_start(self) -> None:
        """セッション開始に失敗した場合のクリーンアップ。"""
        try:
            await self._audio_capture.stop_recording()
        except Exception:
            logger.exception("Failed to stop audio capture during abort")
        if self._stt_client:
            try:
                await self._stt_client.stop()
            except Exception:
                logger.exception("Failed to stop STT during abort")
            self._stt_client = None
        self._vad = None
        self._app_state.current_session = None
        self._app_state.recording = False
        await self._app_state.broadcaster.broadcast(
            "error", {"message": "セッション開始に失敗しました。"}
        )

    async def stop_session(self, *, timed_out: bool = False) -> Session | None:
        """セッションを停止し、最終テキストを組み立てて返す。"""
        async with self._lock:
            if not self._app_state.recording:
                return None

            self._app_state.recording = False

            await self._audio_capture.stop_recording()

            post_processing = bool(
                self._stt_client and self._stt_client.capabilities.post_processing
            )
            if post_processing:
                await self._app_state.broadcaster.broadcast(
                    "processing", {"message": "文字起こし中..."}
                )

            if self._stt_client:
                await self._stt_client.stop()
                self._stt_client = None
            self._vad = None

            if post_processing:
                await self._app_state.broadcaster.broadcast("processing_done", {})

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
                self._app_state.pending_session = session

            self._app_state.current_session = None

            await self._app_state.broadcaster.broadcast("session_end", session_end_data)
            await self._app_state.broadcaster.broadcast("status", {"recording": False})

            if session:
                logger.info(
                    "Session ended: %s (timed_out=%s, segments=%d)",
                    session.id,
                    timed_out,
                    len(session.segments),
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
        """最大セッション時間、または発話終了からの無音タイムアウトで自動停止する。"""
        session_start = time.monotonic()
        while True:
            now = time.monotonic()
            remaining_max = session_start + MAX_SESSION_DURATION_SEC - now
            last_speech = self._vad.last_speech_time if self._vad else session_start
            remaining_silence = last_speech + SILENCE_TIMEOUT_SEC - now
            remaining = min(remaining_max, remaining_silence)
            if remaining <= 0:
                reason = (
                    "max duration" if remaining_max <= remaining_silence else "silence"
                )
                logger.info(
                    "Session timed out (%s) after %.0f seconds",
                    reason,
                    now - session_start,
                )
                await self.stop_session(timed_out=True)
                return
            await asyncio.sleep(remaining)
