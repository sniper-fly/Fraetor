from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.transcript_history.domain.models import FinalizedSession

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState
    from src.dictation.application.segment_accumulator import SegmentAccumulator
    from src.dictation.domain.models import TranscriptionJob

logger = logging.getLogger(__name__)


class TranscriptionQueue:
    """文字起こしジョブをFIFOで直列処理するワーカー。

    録音の開始/停止やマイクには一切関与しない。`RecordingSessionService`
    が `stop_session()` 時点でジョブをenqueueするだけで即座に返り、
    このワーカーが投入順 (=録音開始順) に1件ずつ処理する。ワーカーを
    1本のみに限定することで、複数セッションの完了順が録音開始順と
    崩れないようにしている (FIFO順でtextareaに追記するA案の前提)。
    """

    def __init__(self, app_state: AppState, accumulator: SegmentAccumulator) -> None:
        self._app_state = app_state
        self._accumulator = accumulator
        self._queue: asyncio.Queue[TranscriptionJob] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """ワーカータスクを起動する。"""
        self._worker_task = asyncio.create_task(self._run())

    async def enqueue(self, job: TranscriptionJob) -> None:
        """ジョブをキューに積む (即座に返る)。"""
        await self._queue.put(job)

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._process_job(job)
            except Exception:
                logger.exception("Transcription job failed: session=%s", job.session.id)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: TranscriptionJob) -> None:
        session_id = job.session.id
        post_processing = job.stt_client.capabilities.post_processing
        if post_processing:
            await self._app_state.broadcaster.broadcast(
                "processing", {"session_id": session_id, "message": "文字起こし中..."}
            )

        await job.stt_client.stop()

        if post_processing:
            await self._app_state.broadcaster.broadcast(
                "processing_done", {"session_id": session_id}
            )

        await self._accumulator.drain(job.session, job.event_queue)

        finalized = FinalizedSession.from_recording(
            job.session, ended_at=datetime.now(tz=UTC), timed_out=job.timed_out
        )
        self._app_state.add_pending_session(finalized)

        await self._app_state.broadcaster.broadcast(
            "session_end", {"session_id": finalized.id}
        )

        logger.info(
            "Session transcribed: %s (timed_out=%s, segments=%d)",
            finalized.id,
            job.timed_out,
            len(finalized.segments),
        )

    async def shutdown(self, timeout: float) -> None:
        """残キューの処理完了を待つ (タイムアウト付き)。"""
        if self._worker_task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except TimeoutError:
            logger.warning("TranscriptionQueue shutdown timed out with jobs pending")
        self._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker_task
        self._worker_task = None
