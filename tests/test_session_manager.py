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
    mock_audio_cls: MagicMock,
    *,
    post_processing: bool = False,
) -> tuple[MagicMock, MagicMock]:
    """create_stt_engine と AudioCapture のモックを設定する。"""
    mock_stt = mock_factory.return_value
    mock_stt.start = AsyncMock()
    mock_stt.stop = AsyncMock()
    mock_stt.feed_audio = MagicMock()
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing,
        post_processing=post_processing,
    )
    mock_audio = mock_audio_cls.return_value
    return mock_stt, mock_audio


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.create_stt_engine")
class TestStartSession:
    async def test_creates_session_with_correct_fields(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: セッション開始 → Session 作成"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.start_session()

        assert app_state.recording is True
        session = app_state.current_session
        assert session is not None
        assert session.segments == []
        assert session.ended_at is None
        assert session.timed_out is False

        await sm.stop_session()

    async def test_starts_stt_then_audio(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: Azure STT Streaming 接続 → マイクキャプチャ開始"""
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.start_session()

        mock_stt.start.assert_called_once()
        mock_audio_cls.return_value.start.assert_called_once()
        mock_audio_cls.assert_called_once_with(mock_stt.feed_audio)

        await sm.stop_session()

    async def test_broadcasts_recording_started(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sub = app_state.broadcaster.subscribe()
        sm = SessionManager(app_state)

        await sm.start_session()

        msg = sub.get_nowait()
        assert msg["event"] == "status"
        assert json.loads(msg["data"])["recording"] is True

        await sm.stop_session()

    async def test_ignores_start_when_already_recording(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()
        mock_stt.start.reset_mock()

        await sm.start_session()

        mock_stt.start.assert_not_called()

        await sm.stop_session()


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.create_stt_engine")
class TestStopSession:
    async def test_stops_audio_and_stt(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: 録音停止 → Azure STT切断"""
        mock_stt, mock_audio = _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        await sm.stop_session()

        mock_audio.stop.assert_called_once()
        mock_stt.stop.assert_called_once()
        assert app_state.recording is False

    async def test_returns_finalized_session(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        session = await sm.stop_session()

        assert session is not None
        assert session.ended_at is not None
        assert session.timed_out is False
        assert app_state.current_session is None

    async def test_returns_none_when_not_recording(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)

        result = await sm.stop_session()

        assert result is None

    async def test_broadcasts_session_end_and_status(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
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

    async def test_timed_out_flag_set(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        session = await sm.stop_session(timed_out=True)

        assert session is not None
        assert session.timed_out is True

    async def test_drains_recognized_events_after_event_task_cancelled(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """停止時にキューに残ったrecognizedイベントもセグメントに反映される。"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
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

    async def test_sets_pending_session_on_stop(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """停止時に pending_session にセッションが保存されること"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "テスト"})
        await asyncio.sleep(0.05)

        session = await sm.stop_session()

        assert app_state.pending_session is session
        assert app_state.current_session is None


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.create_stt_engine")
class TestSttEventProcessing:
    async def test_interim_broadcasts_sse(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: interim → SSE("interim") → ブラウザ (グレー)"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
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
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: recognized → SSE → ブラウザ (緑)"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
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

    async def test_segment_ids_increment(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
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
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: 全セグメントのテキスト結合"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
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


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.create_stt_engine")
class TestSessionTimeout:
    @patch("src.session_manager.MAX_SESSION_DURATION_SEC", 0.1)
    async def test_auto_stops_after_max_duration(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """azure-stt-only-spec.md: 最大セッション時間: 3分 → 超過時は自動で録音停止"""
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.start_session()
        assert app_state.recording is True

        await asyncio.sleep(0.2)

        assert app_state.recording is False
        assert app_state.current_session is None
        mock_stt.stop.assert_called_once()


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.create_stt_engine")
class TestSessionStartFailure:
    async def test_stt_failure_aborts_session(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
    ) -> None:
        """Azure STT開始失敗時はセッションを中止する"""
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None

    async def test_stt_failure_broadcasts_error(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
    ) -> None:
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        app_state = AppState()
        sub = app_state.broadcaster.subscribe()
        sm = SessionManager(app_state)

        await sm.start_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        error_msgs = [m for m in messages if m["event"] == "error"]
        assert len(error_msgs) == 1
        assert "失敗" in json.loads(error_msgs[0]["data"])["message"]

    async def test_audio_failure_aborts_session(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
    ) -> None:
        """AudioCapture開始失敗時はセッションを中止する"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_audio_cls.return_value.start.side_effect = RuntimeError("No audio device")
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.create_stt_engine")
class TestPostProcessingNotifications:
    """capabilities.post_processing 駆動の processing イベント通知。"""

    async def test_post_processing_engine_emits_processing_events(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """MAI など post_processing=True のエンジンでは
        stop時に processing/processing_done が発火される。"""
        _setup_mocks(mock_stt_cls, mock_audio_cls, post_processing=True)
        app_state = AppState()
        sm = SessionManager(app_state)
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
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """Azure など post_processing=False のエンジンでは
        processing 系イベントは発火されない。"""
        _setup_mocks(mock_stt_cls, mock_audio_cls, post_processing=False)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()

        await sm.stop_session()

        messages: list[dict[str, str]] = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "processing" not in events
        assert "processing_done" not in events
