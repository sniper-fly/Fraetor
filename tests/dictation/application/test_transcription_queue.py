from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.dictation.application.app_state import AppState
from src.dictation.application.segment_accumulator import SegmentAccumulator
from src.dictation.application.transcription_queue import TranscriptionQueue
from src.dictation.domain.models import RecordingSession, TranscriptionJob
from src.dictation.domain.ports import SttCapabilities, SttEnginePort
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster


def _make_job(
    *,
    session_id: str = "session-1",
    post_processing: bool = True,
    stop_side_effect: object = None,
) -> tuple[TranscriptionJob, MagicMock]:
    mock_stt = MagicMock(spec=SttEnginePort)
    mock_stt.stop = AsyncMock(side_effect=stop_side_effect)
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing, post_processing=post_processing
    )
    session = RecordingSession(
        id=session_id, segments=[], started_at=datetime.now(tz=UTC)
    )
    job = TranscriptionJob(
        session=session,
        stt_client=mock_stt,
        event_queue=asyncio.Queue(),
        timed_out=False,
    )
    return job, mock_stt


def _make_queue() -> tuple[TranscriptionQueue, AppState]:
    app_state = AppState(broadcaster=SSEBroadcaster())
    accumulator = SegmentAccumulator(app_state.broadcaster)
    return TranscriptionQueue(app_state, accumulator), app_state


class TestProcessJob:
    async def test_post_processing_engine_emits_processing_events(self) -> None:
        queue, app_state = _make_queue()
        sub = app_state.broadcaster.subscribe()
        job, _ = _make_job(post_processing=True)
        queue.start()

        await queue.enqueue(job)
        await asyncio.sleep(0.05)

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" in events
        assert "processing_done" in events
        assert events.index("processing") < events.index("processing_done")

        await queue.shutdown(timeout=1)

    async def test_streaming_engine_does_not_emit_processing_events(self) -> None:
        queue, app_state = _make_queue()
        sub = app_state.broadcaster.subscribe()
        job, _ = _make_job(post_processing=False)
        queue.start()

        await queue.enqueue(job)
        await asyncio.sleep(0.05)

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" not in events
        assert "processing_done" not in events

        await queue.shutdown(timeout=1)

    async def test_drains_event_queue_into_session_segments(self) -> None:
        queue, app_state = _make_queue()
        job, _ = _make_job()
        job.event_queue.put_nowait({"type": "recognized", "text": "ドレイン"})
        queue.start()

        await queue.enqueue(job)
        await asyncio.sleep(0.05)

        assert app_state.pending_sessions[-1].full_text == "ドレイン"

        await queue.shutdown(timeout=1)

    async def test_sets_pending_session_after_processing(self) -> None:
        queue, app_state = _make_queue()
        job, _ = _make_job(session_id="session-xyz")
        queue.start()

        await queue.enqueue(job)
        await asyncio.sleep(0.05)

        assert app_state.pending_sessions[-1].id == "session-xyz"

        await queue.shutdown(timeout=1)

    async def test_broadcasts_session_end(self) -> None:
        queue, app_state = _make_queue()
        sub = app_state.broadcaster.subscribe()
        job, _ = _make_job()
        queue.start()

        await queue.enqueue(job)
        await asyncio.sleep(0.05)

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "session_end" in events

        await queue.shutdown(timeout=1)

    async def test_timed_out_flag_propagated_to_finalized_session(self) -> None:
        queue, app_state = _make_queue()
        mock_stt = MagicMock(spec=SttEnginePort)
        mock_stt.stop = AsyncMock()
        mock_stt.capabilities = SttCapabilities(streaming=False, post_processing=True)
        session = RecordingSession(
            id="session-1", segments=[], started_at=datetime.now(tz=UTC)
        )
        job = TranscriptionJob(
            session=session,
            stt_client=mock_stt,
            event_queue=asyncio.Queue(),
            timed_out=True,
        )
        queue.start()

        await queue.enqueue(job)
        await asyncio.sleep(0.05)

        assert app_state.pending_sessions[-1].timed_out is True

        await queue.shutdown(timeout=1)


class TestFifoOrdering:
    async def test_processes_jobs_in_enqueue_order(self) -> None:
        """ワーカーは1本のみのため、投入順(=録音開始順)で完了する。
        後発(second)が完了しても先発(first)は上書きされず、両方が
        pending_sessionsに個別に残る (session_id取り違えの回帰テスト)。"""
        queue, app_state = _make_queue()
        processed_order: list[str] = []

        job1, mock_stt1 = _make_job(session_id="first")
        job2, mock_stt2 = _make_job(session_id="second")

        async def slow_stop() -> None:
            await asyncio.sleep(0.05)
            processed_order.append("first")

        async def fast_stop() -> None:
            processed_order.append("second")

        mock_stt1.stop = slow_stop
        mock_stt2.stop = fast_stop
        queue.start()

        await queue.enqueue(job1)
        await queue.enqueue(job2)
        await asyncio.sleep(0.2)

        assert processed_order == ["first", "second"]
        pending_ids = [s.id for s in app_state.pending_sessions]
        assert pending_ids == ["first", "second"]

        await queue.shutdown(timeout=1)

    async def test_exception_in_one_job_does_not_stop_worker(self) -> None:
        queue, app_state = _make_queue()
        job1, mock_stt1 = _make_job(session_id="failing")
        job2, _ = _make_job(session_id="succeeding")
        mock_stt1.stop = AsyncMock(side_effect=RuntimeError("boom"))
        queue.start()

        await queue.enqueue(job1)
        await queue.enqueue(job2)
        await asyncio.sleep(0.1)

        pending_ids = [s.id for s in app_state.pending_sessions]
        assert pending_ids == ["succeeding"]

        await queue.shutdown(timeout=1)

    async def test_no_event_queue_crosstalk_between_sessions(self) -> None:
        """セッションごとに独立したevent_queueを使うため、結果が混線しない。
        両方の処理完了後、それぞれのセッションが個別にpending_sessionsに残る。"""
        queue, app_state = _make_queue()
        job1, mock_stt1 = _make_job(session_id="slow")
        job2, _mock_stt2 = _make_job(session_id="fast")
        job1.event_queue.put_nowait({"type": "recognized", "text": "slowの結果"})
        job2.event_queue.put_nowait({"type": "recognized", "text": "fastの結果"})

        slow_release = asyncio.Event()

        async def slow_stop() -> None:
            await slow_release.wait()

        mock_stt1.stop = slow_stop
        queue.start()

        await queue.enqueue(job1)
        await queue.enqueue(job2)
        await asyncio.sleep(0.05)
        # job1がまだ処理中の間、job2はキューで待機しておりevent_queueは混線しない
        assert app_state.pending_sessions == []

        slow_release.set()
        await asyncio.sleep(0.1)

        pending_by_id = {s.id: s for s in app_state.pending_sessions}
        assert pending_by_id.keys() == {"slow", "fast"}
        assert pending_by_id["slow"].full_text == "slowの結果"
        assert pending_by_id["fast"].full_text == "fastの結果"

        await queue.shutdown(timeout=1)


class TestConcurrentSessionsPending:
    async def test_three_consecutive_sessions_all_remain_distinct(self) -> None:
        """3セッション分のジョブが連続処理されても、いずれも上書き・欠落せず
        pending_sessionsに正しく残る (回帰テスト)。"""
        queue, app_state = _make_queue()
        jobs = [_make_job(session_id=f"session-{i}")[0] for i in range(3)]
        for i, job in enumerate(jobs):
            job.event_queue.put_nowait({"type": "recognized", "text": f"結果{i}"})
        queue.start()

        for job in jobs:
            await queue.enqueue(job)
        await asyncio.sleep(0.2)

        pending_by_id = {s.id: s for s in app_state.pending_sessions}
        assert pending_by_id.keys() == {"session-0", "session-1", "session-2"}
        for i in range(3):
            assert pending_by_id[f"session-{i}"].full_text == f"結果{i}"

        await queue.shutdown(timeout=1)


class TestShutdown:
    async def test_waits_for_pending_jobs(self) -> None:
        queue, app_state = _make_queue()
        job, mock_stt = _make_job()
        release = asyncio.Event()

        async def delayed_stop() -> None:
            await release.wait()

        mock_stt.stop = delayed_stop
        queue.start()
        await queue.enqueue(job)

        shutdown_task = asyncio.create_task(queue.shutdown(timeout=1))
        await asyncio.sleep(0.05)
        assert not shutdown_task.done()

        release.set()
        await shutdown_task

        assert len(app_state.pending_sessions) == 1

    async def test_times_out_with_jobs_still_pending(self) -> None:
        queue, _ = _make_queue()
        job, mock_stt = _make_job()

        async def never_returns() -> None:
            await asyncio.sleep(10)

        mock_stt.stop = never_returns
        queue.start()
        await queue.enqueue(job)

        await queue.shutdown(timeout=0.05)
