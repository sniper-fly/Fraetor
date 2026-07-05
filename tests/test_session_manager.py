from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.session_manager import SessionManager
from src.state import AppState
from src.stt_base import SttCapabilities


def _setup_mocks(
    mock_factory: MagicMock,
    *,
    post_processing: bool = False,
) -> tuple[MagicMock, MagicMock]:
    """MaiTranscribeClient のモックと AudioCapture モック (注入用) を設定する。"""
    mock_stt = mock_factory.return_value
    mock_stt.start = AsyncMock()
    mock_stt.stop = AsyncMock()
    mock_stt.feed_audio = MagicMock()
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing,
        post_processing=post_processing,
    )
    mock_audio = MagicMock()
    mock_audio.start_recording = AsyncMock()
    mock_audio.stop_recording = AsyncMock()
    return mock_stt, mock_audio


@patch("src.session_manager.MaiTranscribeClient")
class TestStartSession:
    async def test_creates_session_with_correct_fields(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """セッション開始 → Session 作成"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()

        assert app_state.recording is True
        session = app_state.current_session
        assert session is not None
        assert session.segments == []
        assert session.ended_at is None
        assert session.timed_out is False

        await sm.stop_session()

    async def test_starts_stt_then_audio(self, mock_stt_cls: MagicMock) -> None:
        """STT 接続 → 常駐ストリームを開いて録音開始"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()

        mock_stt.start.assert_called_once()
        mock_audio.start_recording.assert_awaited_once_with(mock_stt.feed_audio)

        await sm.stop_session()

    async def test_broadcasts_recording_started(self, mock_stt_cls: MagicMock) -> None:
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sub = app_state.broadcaster.subscribe()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()

        msg = sub.get_nowait()
        assert msg["event"] == "status"
        assert json.loads(msg["data"])["recording"] is True

        await sm.stop_session()

    async def test_ignores_start_when_already_recording(
        self, mock_stt_cls: MagicMock
    ) -> None:
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()
        mock_stt.start.reset_mock()

        await sm.start_session()

        mock_stt.start.assert_not_called()

        await sm.stop_session()


@patch("src.session_manager.MaiTranscribeClient")
class TestStopSession:
    async def test_stops_recording_and_stt(self, mock_stt_cls: MagicMock) -> None:
        """録音停止 → STT切断。ストリーム自体は閉じない (常駐)"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        await sm.stop_session()

        mock_audio.stop_recording.assert_awaited_once()
        mock_stt.stop.assert_called_once()
        assert app_state.recording is False

    async def test_returns_finalized_session(self, mock_stt_cls: MagicMock) -> None:
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        session = await sm.stop_session()

        assert session is not None
        assert session.ended_at is not None
        assert session.timed_out is False
        assert app_state.current_session is None

    async def test_returns_none_when_not_recording(
        self, mock_stt_cls: MagicMock
    ) -> None:
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        result = await sm.stop_session()

        assert result is None

    async def test_broadcasts_session_end_and_status(
        self, mock_stt_cls: MagicMock
    ) -> None:
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()

        await sm.stop_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "session_end" in events
        assert "status" in events
        status_msg = next(m for m in messages if m["event"] == "status")
        assert json.loads(status_msg["data"])["recording"] is False

    async def test_timed_out_flag_set(self, mock_stt_cls: MagicMock) -> None:
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        session = await sm.stop_session(timed_out=True)

        assert session is not None
        assert session.timed_out is True

    async def test_drains_recognized_events_after_event_task_cancelled(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """停止時にキューに残ったrecognizedイベントもセグメントに反映される。"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        assert sm._event_task is not None
        sm._event_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sm._event_task
        sm._event_task = None

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "ドレイン"})
        app_state.stt_event_queue.put_nowait({"type": "interim", "text": "中間は無視"})

        session = await sm.stop_session()

        assert session is not None
        assert len(session.segments) == 1
        assert session.segments[0].text == "ドレイン"

    async def test_sets_pending_session_on_stop(self, mock_stt_cls: MagicMock) -> None:
        """停止時に pending_session にセッションが保存されること"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "テスト"})
        await asyncio.sleep(0.05)

        session = await sm.stop_session()

        assert app_state.pending_session is session
        assert app_state.current_session is None


@patch("src.session_manager.MaiTranscribeClient")
class TestSttEventProcessing:
    async def test_interim_broadcasts_sse(self, mock_stt_cls: MagicMock) -> None:
        """interim → SSE("interim") → ブラウザ (グレー)"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()
        while not sub.empty():
            sub.get_nowait()

        app_state.stt_event_queue.put_nowait({"type": "interim", "text": "中間結果"})
        await asyncio.sleep(0.05)

        msg = sub.get_nowait()
        assert msg["event"] == "interim"
        assert json.loads(msg["data"])["text"] == "中間結果"

        await sm.stop_session()

    async def test_recognized_creates_segment_and_broadcasts(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """recognized → SSE → ブラウザ (緑)"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()
        while not sub.empty():
            sub.get_nowait()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "認識結果"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 1
        seg = session.segments[0]
        assert seg.id == 0
        assert seg.text == "認識結果"

        msg = sub.get_nowait()
        assert msg["event"] == "recognized"
        data = json.loads(msg["data"])
        assert data["segment_id"] == 0
        assert data["text"] == "認識結果"

        await sm.stop_session()

    async def test_segment_ids_increment(self, mock_stt_cls: MagicMock) -> None:
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "1つ目"})
        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "2つ目"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 2
        assert session.segments[0].id == 0
        assert session.segments[1].id == 1

        await sm.stop_session()

    async def test_full_text_assembled_from_segments(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """全セグメントのテキスト結合"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "こんにちは。"}
        )
        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "お元気ですか。"}
        )
        await asyncio.sleep(0.05)

        session = await sm.stop_session()
        assert session is not None
        assert session.full_text == "こんにちは。お元気ですか。"


@patch("src.session_manager.MaiTranscribeClient")
class TestSessionTimeout:
    @patch("src.session_manager.MAX_SESSION_DURATION_SEC", 0.1)
    async def test_auto_stops_after_max_duration(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """最大セッション時間: 3分 → 超過時は自動で録音停止"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()
        assert app_state.recording is True

        await asyncio.sleep(0.2)

        assert app_state.recording is False
        assert app_state.current_session is None
        mock_stt.stop.assert_called_once()


@patch("src.session_manager.MaiTranscribeClient")
class TestSessionStartFailure:
    async def test_stt_failure_aborts_session(self, mock_stt_cls: MagicMock) -> None:
        """STT開始失敗時はセッションを中止する"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls)
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None

    async def test_stt_failure_broadcasts_error(self, mock_stt_cls: MagicMock) -> None:
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls)
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        app_state = AppState()
        sub = app_state.broadcaster.subscribe()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        error_msgs = [m for m in messages if m["event"] == "error"]
        assert len(error_msgs) == 1
        assert "失敗" in json.loads(error_msgs[0]["data"])["message"]

    async def test_stream_open_failure_aborts_session(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """ストリームを開けない場合はセッションを中止する"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        mock_audio.start_recording = AsyncMock(
            side_effect=RuntimeError("No audio device")
        )
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None

    async def test_stream_open_failure_can_recover_on_next_start(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """ストリームを開けず中止しても、次の start_session で再試行できる"""
        _, mock_audio = _setup_mocks(mock_stt_cls)
        mock_audio.start_recording = AsyncMock(
            side_effect=[RuntimeError("No audio device"), None]
        )
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)

        await sm.start_session()
        assert app_state.recording is False

        await sm.start_session()
        assert app_state.recording is True

        await sm.stop_session()


@patch("src.session_manager.MaiTranscribeClient")
class TestPostProcessingNotifications:
    """capabilities.post_processing 駆動の processing イベント通知。"""

    async def test_post_processing_engine_emits_processing_events(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """MAI など post_processing=True のエンジンでは
        stop時に processing/processing_done が発火される。"""
        _, mock_audio = _setup_mocks(mock_stt_cls, post_processing=True)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()

        await sm.stop_session()

        messages: list[dict[str, str]] = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" in events
        assert "processing_done" in events
        # processing → processing_done の順序を保証
        assert events.index("processing") < events.index("processing_done")

    async def test_streaming_engine_does_not_emit_processing_events(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """post_processing=False のエンジンでは processing 系イベントは発火されない。"""
        _, mock_audio = _setup_mocks(mock_stt_cls, post_processing=False)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()

        await sm.stop_session()

        messages: list[dict[str, str]] = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" not in events
        assert "processing_done" not in events


@patch("src.session_manager.MaiTranscribeClient")
class TestConcurrentStartStop:
    """stop_session中にstart_sessionが呼ばれた場合の排他制御テスト。"""

    async def test_start_waits_for_stop_to_complete(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """stop_session中のSTT API呼び出し中にstart_sessionが呼ばれた場合、
        Lockにより待機し、stop完了後に新セッションが正常に開始される。"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls, post_processing=True)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        assert app_state.current_session is not None
        first_session_id = app_state.current_session.id

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        stop_task = asyncio.create_task(sm.stop_session())
        await stt_stop_entered.wait()

        # stop中にstartを試みる(Lockで待機するはず)
        start_task = asyncio.create_task(sm.start_session())
        await asyncio.sleep(0.05)
        # startはまだ完了していない
        assert not start_task.done()
        assert app_state.recording is False

        # stopを完了させる
        stt_stop_proceed.set()
        stopped_session = await stop_task
        assert stopped_session is not None
        assert stopped_session.id == first_session_id

        # start_sessionがLock解放後に実行される
        await start_task
        assert app_state.recording is True
        assert app_state.current_session is not None
        assert app_state.current_session.id != first_session_id

        await sm.stop_session()

    async def test_new_session_resources_not_clobbered(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """排他制御により新セッションのリソースが旧stop処理に破壊されない。"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls, post_processing=True)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        stop_task = asyncio.create_task(sm.stop_session())
        await stt_stop_entered.wait()

        start_task = asyncio.create_task(sm.start_session())
        await asyncio.sleep(0.05)

        stt_stop_proceed.set()
        await stop_task
        await start_task

        # 新セッションのevent_taskとtimeout_taskが存在する
        assert sm._event_task is not None
        assert not sm._event_task.done()
        assert sm._timeout_task is not None
        assert not sm._timeout_task.done()
        assert sm._stt_client is not None

        await sm.stop_session()

    async def test_concurrent_double_stop_is_idempotent(
        self, mock_stt_cls: MagicMock
    ) -> None:
        """同時に2回stop_sessionが呼ばれても、2回目はNoneを返す。"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls, post_processing=True)
        app_state = AppState()
        sm = SessionManager(app_state, mock_audio)
        await sm.start_session()

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        stop_task1 = asyncio.create_task(sm.stop_session())
        await stt_stop_entered.wait()

        stop_task2 = asyncio.create_task(sm.stop_session())
        await asyncio.sleep(0.05)
        assert not stop_task2.done()

        stt_stop_proceed.set()
        result1 = await stop_task1
        result2 = await stop_task2

        assert result1 is not None
        assert result2 is None
