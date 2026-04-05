from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from src.audio import AudioCapture
from src.clipboard import copy_and_paste
from src.config import CORRECTION_TIMEOUT_SEC, MAX_SESSION_DURATION_SEC
from src.correction import GeminiCorrectionClient
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
    校正ONの場合は GeminiCorrectionClient で校正を行う。
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._stt_client: AzureSttClient | None = None
        self._audio_capture: AudioCapture | None = None
        self._correction_client: GeminiCorrectionClient | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._correction_task: asyncio.Task[None] | None = None
        self._next_segment_id: int = 0

    async def start_session(self) -> None:
        """セッションを開始し、録音を開始する。"""
        if self._app_state.recording:
            return

        session = Session(
            id=str(uuid4()),
            segments=[],
            started_at=datetime.now(tz=UTC),
            correction_enabled=self._app_state.correction_enabled,
        )
        self._app_state.current_session = session
        self._app_state.recording = True
        self._next_segment_id = 0

        # design.md: Gemini Live API セッション接続(校正ONの場合)
        if session.correction_enabled:
            self._correction_client = GeminiCorrectionClient()
            await self._correction_client.connect()
            self._correction_task = asyncio.create_task(self._correction_worker())

        # design.md: Azure STT Streaming 接続 → マイクキャプチャ開始
        self._stt_client = AzureSttClient(self._app_state.stt_event_queue)
        await self._stt_client.start()

        self._audio_capture = AudioCapture(self._stt_client.write_audio)
        self._audio_capture.start()

        self._event_task = asyncio.create_task(self._process_stt_events())
        self._timeout_task = asyncio.create_task(self._session_timeout())

        await self._app_state.broadcaster.broadcast("status", {"recording": True})
        logger.info("Session started: %s", session.id)

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

        # design.md: 未校正セグメントの校正完了を待機(タイムアウト10秒)
        await self._wait_for_corrections()

        session = self._app_state.current_session
        if session:
            session.ended_at = datetime.now(tz=UTC)
            session.timed_out = timed_out
            if session.full_text:
                try:
                    await copy_and_paste(session.full_text)
                except Exception:
                    logger.exception("Failed to copy and paste session text")

        self._app_state.current_session = None

        await self._app_state.broadcaster.broadcast("session_end", {})
        await self._app_state.broadcaster.broadcast("status", {"recording": False})

        # design.md: セッション終了時に JSONL に保存
        if session:
            try:
                save_session(session)
            except Exception:
                logger.exception("Failed to save session history")
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
                    if self._correction_client:
                        # design.md: recognized → Gemini Live API にテキスト送信
                        await self._app_state.correction_queue.put(segment)
                    else:
                        # design.md: 校正OFF → そのまま確定テキストとして表示
                        await self._app_state.broadcaster.broadcast(
                            "corrected",
                            {
                                "segment_id": segment.id,
                                "text": segment.corrected_text,
                            },
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
            if self._correction_client:
                await self._app_state.correction_queue.put(segment)
            else:
                await self._app_state.broadcaster.broadcast(
                    "corrected",
                    {"segment_id": segment.id, "text": segment.corrected_text},
                )

    def _add_segment(self, text: str) -> Segment:
        """認識済みテキストからセグメントを作成し、セッションに追加する。"""
        correcting = self._correction_client is not None
        segment = Segment(
            id=self._next_segment_id,
            status="correcting" if correcting else "corrected",
            raw_text=text,
            corrected_text="" if correcting else text,
        )
        self._next_segment_id += 1
        if self._app_state.current_session:
            self._app_state.current_session.segments.append(segment)
        return segment

    async def _correction_worker(self) -> None:
        """correction_queueからセグメントを取り出し、Geminiで直列に校正する。

        design.md: 直列方式(1セグメントずつ送信 → turn_complete 待ち → 次セグメント)
        """
        while True:
            segment = await self._app_state.correction_queue.get()
            if segment is None:
                break
            try:
                corrected = await self._correction_client.correct(  # type: ignore[union-attr]
                    segment.raw_text
                )
                segment.corrected_text = corrected
            except Exception:
                logger.exception("Correction failed for segment %d", segment.id)
                segment.corrected_text = segment.raw_text
            segment.status = "corrected"
            await self._app_state.broadcaster.broadcast(
                "corrected",
                {"segment_id": segment.id, "text": segment.corrected_text},
            )

    async def _wait_for_corrections(self) -> None:
        """校正ワーカーの完了を待機し、タイムアウト時はraw_textにフォールバックする。"""
        if not self._correction_client:
            return

        # センチネルを送信して「これ以上セグメントはない」と通知
        await self._app_state.correction_queue.put(None)

        if self._correction_task:
            try:
                await asyncio.wait_for(
                    self._correction_task, timeout=CORRECTION_TIMEOUT_SEC
                )
            except TimeoutError:
                logger.warning(
                    "Correction timed out after %ds, using raw_text",
                    CORRECTION_TIMEOUT_SEC,
                )
                self._correction_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._correction_task

                # design.md: タイムアウト → raw_text でペースト
                if self._app_state.current_session:
                    for seg in self._app_state.current_session.segments:
                        if seg.status == "correcting":
                            seg.corrected_text = seg.raw_text
                            seg.status = "corrected"
            self._correction_task = None

        await self._correction_client.disconnect()
        self._correction_client = None

    async def _session_timeout(self) -> None:
        """MAX_SESSION_DURATION_SEC 後にセッションを自動停止する。"""
        await asyncio.sleep(MAX_SESSION_DURATION_SEC)
        logger.info("Session timed out after %d seconds", MAX_SESSION_DURATION_SEC)
        await self.stop_session(timed_out=True)
