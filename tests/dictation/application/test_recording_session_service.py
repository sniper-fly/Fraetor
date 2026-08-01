from __future__ import annotations

import asyncio
import contextlib
import json
import time
from unittest.mock import AsyncMock, MagicMock

from src.dictation.application.app_state import AppState
from src.dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from src.dictation.application.recording_session_service import (
    RecordingSessionService,
)
from src.dictation.application.stt_event_relay import SttEventRelay
from src.dictation.domain.ports import SttCapabilities
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster

_MAX_DURATION_SEC = 600
_SILENCE_TIMEOUT_SEC = 120


def _make_service(
    *,
    max_duration_sec: float = _MAX_DURATION_SEC,
    silence_timeout_sec: float = _SILENCE_TIMEOUT_SEC,
    post_processing: bool = False,
    stt_start_side_effect: Exception | None = None,
    audio_start_side_effect: Exception | None = None,
) -> tuple[RecordingSessionService, AppState, MagicMock]:
    app_state = AppState(broadcaster=SSEBroadcaster())

    mock_stt = MagicMock()
    mock_stt.start = AsyncMock(side_effect=stt_start_side_effect)
    mock_stt.stop = AsyncMock()
    mock_stt.feed_audio = MagicMock()
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing, post_processing=post_processing
    )
    mock_vad = MagicMock()
    mock_vad.last_speech_time = time.monotonic()
    mock_audio = MagicMock()
    mock_audio.start_recording = AsyncMock(side_effect=audio_start_side_effect)
    mock_audio.stop_recording = AsyncMock()

    audio_pipeline = AudioPipelineCoordinator(
        mock_audio, lambda: mock_stt, lambda: mock_vad
    )
    event_relay = SttEventRelay(app_state)
    service = RecordingSessionService(
        app_state,
        audio_pipeline,
        event_relay,
        max_session_duration_sec=max_duration_sec,
        silence_timeout_sec=silence_timeout_sec,
    )
    return service, app_state, mock_stt


class TestStartSession:
    async def test_creates_session_with_correct_fields(self) -> None:
        """セッション開始 → RecordingSession 作成"""
        service, app_state, _ = _make_service()

        await service.start_session()

        assert app_state.recording is True
        session = app_state.current_session
        assert session is not None
        assert session.segments == []

        await service.stop_session()

    async def test_broadcasts_recording_started(self) -> None:
        service, app_state, _ = _make_service()
        sub = app_state.broadcaster.subscribe()

        await service.start_session()

        msg = sub.get_nowait()
        assert msg["event"] == "status"
        assert json.loads(msg["data"])["recording"] is True

        await service.stop_session()

    async def test_ignores_start_when_already_recording(self) -> None:
        service, _, mock_stt = _make_service()
        await service.start_session()
        mock_stt.start.reset_mock()

        await service.start_session()

        mock_stt.start.assert_not_called()

        await service.stop_session()


class TestStopSession:
    async def test_stops_recording_and_stt(self) -> None:
        service, app_state, mock_stt = _make_service()
        await service.start_session()

        await service.stop_session()

        mock_stt.stop.assert_called_once()
        assert app_state.recording is False

    async def test_returns_finalized_session(self) -> None:
        service, app_state, _ = _make_service()
        await service.start_session()

        finalized = await service.stop_session()

        assert finalized is not None
        assert finalized.ended_at is not None
        assert finalized.timed_out is False
        assert app_state.current_session is None

    async def test_returns_none_when_not_recording(self) -> None:
        service, _, _ = _make_service()

        result = await service.stop_session()

        assert result is None

    async def test_broadcasts_session_end_and_status(self) -> None:
        service, app_state, _ = _make_service()
        await service.start_session()
        sub = app_state.broadcaster.subscribe()

        await service.stop_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "session_end" in events
        assert "status" in events
        status_msg = next(m for m in messages if m["event"] == "status")
        assert json.loads(status_msg["data"])["recording"] is False

    async def test_timed_out_flag_set(self) -> None:
        service, _, _ = _make_service()
        await service.start_session()

        finalized = await service.stop_session(timed_out=True)

        assert finalized is not None
        assert finalized.timed_out is True

    async def test_drains_recognized_events_after_event_task_cancelled(self) -> None:
        """停止時にキューに残ったrecognizedイベントもセグメントに反映される。"""
        service, app_state, _ = _make_service()
        await service.start_session()

        event_relay = service._event_relay
        assert event_relay._task is not None
        event_relay._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await event_relay._task
        event_relay._task = None

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "ドレイン"})
        app_state.stt_event_queue.put_nowait({"type": "interim", "text": "中間は無視"})

        finalized = await service.stop_session()

        assert finalized is not None
        assert len(finalized.segments) == 1
        assert finalized.segments[0].text == "ドレイン"

    async def test_sets_pending_session_on_stop(self) -> None:
        """停止時に pending_session にセッションが保存されること"""
        service, app_state, _ = _make_service()
        await service.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "テスト"})
        await asyncio.sleep(0.05)

        finalized = await service.stop_session()

        assert app_state.pending_session is finalized
        assert app_state.current_session is None


class TestSttEventProcessing:
    async def test_full_text_assembled_from_segments(self) -> None:
        """全セグメントのテキスト結合"""
        service, app_state, _ = _make_service()
        await service.start_session()

        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "こんにちは。"}
        )
        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "お元気ですか。"}
        )
        await asyncio.sleep(0.05)

        finalized = await service.stop_session()
        assert finalized is not None
        assert finalized.full_text == "こんにちは。お元気ですか。"


class TestSessionTimeout:
    async def test_auto_stops_after_max_duration(self) -> None:
        """最大セッション時間経過 → 超過時は自動で録音停止"""
        service, app_state, mock_stt = _make_service(
            max_duration_sec=0.1, silence_timeout_sec=10
        )

        await service.start_session()
        assert app_state.recording is True

        await asyncio.sleep(0.2)

        assert app_state.recording is False
        assert app_state.current_session is None
        mock_stt.stop.assert_called_once()

    async def test_auto_stops_after_silence_timeout(self) -> None:
        """発話なしのまま silence_timeout_sec 経過 → 自動で録音停止"""
        service, app_state, _ = _make_service(
            max_duration_sec=10, silence_timeout_sec=0.1
        )

        await service.start_session()
        assert app_state.recording is True

        await asyncio.sleep(0.2)

        assert app_state.recording is False
        assert app_state.current_session is None


class TestSessionStartFailure:
    async def test_stt_failure_aborts_session(self) -> None:
        """STT開始失敗時はセッションを中止する"""
        service, app_state, _ = _make_service(
            stt_start_side_effect=RuntimeError("Auth failed")
        )

        await service.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None

    async def test_stt_failure_broadcasts_error(self) -> None:
        service, app_state, _ = _make_service(
            stt_start_side_effect=RuntimeError("Auth failed")
        )
        sub = app_state.broadcaster.subscribe()

        await service.start_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        error_msgs = [m for m in messages if m["event"] == "error"]
        assert len(error_msgs) == 1
        assert "失敗" in json.loads(error_msgs[0]["data"])["message"]

    async def test_stream_open_failure_aborts_session(self) -> None:
        """ストリームを開けない場合はセッションを中止する"""
        service, app_state, _ = _make_service(
            audio_start_side_effect=RuntimeError("No audio device")
        )

        await service.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None


class TestPostProcessingNotifications:
    """capabilities.post_processing 駆動の processing イベント通知。"""

    async def test_post_processing_engine_emits_processing_events(self) -> None:
        """MAI など post_processing=True のエンジンでは
        stop時に processing/processing_done が発火される。"""
        service, app_state, _ = _make_service(post_processing=True)
        await service.start_session()
        sub = app_state.broadcaster.subscribe()

        await service.stop_session()

        messages: list[dict[str, str]] = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" in events
        assert "processing_done" in events
        assert events.index("processing") < events.index("processing_done")

    async def test_streaming_engine_does_not_emit_processing_events(self) -> None:
        """post_processing=False のエンジンでは processing 系イベントは発火されない。"""
        service, app_state, _ = _make_service(post_processing=False)
        await service.start_session()
        sub = app_state.broadcaster.subscribe()

        await service.stop_session()

        messages: list[dict[str, str]] = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" not in events
        assert "processing_done" not in events


class TestConcurrentStartStop:
    """stop_session中にstart_sessionが呼ばれた場合の排他制御テスト。"""

    async def test_start_waits_for_stop_to_complete(self) -> None:
        """stop_session中のSTT API呼び出し中にstart_sessionが呼ばれた場合、
        Lockにより待機し、stop完了後に新セッションが正常に開始される。"""
        service, app_state, mock_stt = _make_service(post_processing=True)
        await service.start_session()

        assert app_state.current_session is not None
        first_session_id = app_state.current_session.id

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        stop_task = asyncio.create_task(service.stop_session())
        await stt_stop_entered.wait()

        start_task = asyncio.create_task(service.start_session())
        await asyncio.sleep(0.05)
        assert not start_task.done()
        assert app_state.recording is False

        stt_stop_proceed.set()
        stopped_session = await stop_task
        assert stopped_session is not None
        assert stopped_session.id == first_session_id

        await start_task
        assert app_state.recording is True
        assert app_state.current_session is not None
        assert app_state.current_session.id != first_session_id

        await service.stop_session()

    async def test_concurrent_double_stop_is_idempotent(self) -> None:
        """同時に2回stop_sessionが呼ばれても、2回目はNoneを返す。"""
        service, _, mock_stt = _make_service(post_processing=True)
        await service.start_session()

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        stop_task1 = asyncio.create_task(service.stop_session())
        await stt_stop_entered.wait()

        stop_task2 = asyncio.create_task(service.stop_session())
        await asyncio.sleep(0.05)
        assert not stop_task2.done()

        stt_stop_proceed.set()
        result1 = await stop_task1
        result2 = await stop_task2

        assert result1 is not None
        assert result2 is None
