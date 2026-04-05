from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest

from src.session_manager import SessionManager
from src.state import AppState


@pytest.fixture(autouse=True)
def _mock_copy_and_paste() -> Generator[None]:
    with patch("src.session_manager.copy_and_paste", new_callable=AsyncMock):
        yield


@pytest.fixture(autouse=True)
def _mock_save_session() -> Generator[None]:
    with patch("src.session_manager.save_session"):
        yield


@pytest.fixture(autouse=True)
def mock_correction_cls() -> Generator[MagicMock]:
    mock_cls = MagicMock()
    mock_cls.return_value.connect = AsyncMock()
    mock_cls.return_value.correct = AsyncMock(side_effect=lambda text: text)
    mock_cls.return_value.disconnect = AsyncMock()
    with patch("src.session_manager.GeminiCorrectionClient", mock_cls):
        yield mock_cls


def _setup_mocks(
    mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
) -> tuple[MagicMock, MagicMock]:
    """AzureSttClient と AudioCapture のモックを設定する。"""
    mock_stt = mock_stt_cls.return_value
    mock_stt.start = AsyncMock()
    mock_stt.stop = AsyncMock()
    mock_stt.write_audio = MagicMock()
    mock_audio = mock_audio_cls.return_value
    return mock_stt, mock_audio


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestStartSession:
    async def test_creates_session_with_correct_fields(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """design.md: セッション開始 → Session 作成、correction_enabled 反映"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        app_state.correction_enabled = False
        sm = SessionManager(app_state)

        await sm.start_session()

        assert app_state.recording is True
        session = app_state.current_session
        assert session is not None
        assert session.correction_enabled is False
        assert session.segments == []
        assert session.ended_at is None
        assert session.timed_out is False

        await sm.stop_session()

    async def test_starts_stt_then_audio(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """design.md: Azure STT Streaming 接続 → マイクキャプチャ開始"""
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.start_session()

        mock_stt.start.assert_called_once()
        mock_audio_cls.return_value.start.assert_called_once()
        mock_audio_cls.assert_called_once_with(mock_stt.write_audio)

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

    async def test_correction_enabled_captured_at_session_start(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """design.md: 校正 ON/OFF → 次回セッション(次回録音開始)から反映"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        app_state.correction_enabled = True
        sm = SessionManager(app_state)

        await sm.start_session()

        # セッション開始後に変更しても、現セッションには影響しない
        app_state.correction_enabled = False
        assert app_state.current_session is not None
        assert app_state.current_session.correction_enabled is True

        await sm.stop_session()


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestStopSession:
    async def test_stops_audio_and_stt(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """design.md: 録音停止 → Azure STT切断"""
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

        # event_task を先にキャンセルして、ドレインが動作することを検証
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
        assert session.segments[0].raw_text == "ドレイン"


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestSttEventProcessing:
    async def test_interim_broadcasts_sse(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """design.md: interim → SSE("interim") → ブラウザ (グレー)"""
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
        """design.md: recognized → SSE("corrected", seg-N) → ブラウザ (緑)"""
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
        assert seg.status == "corrected"
        assert seg.raw_text == "認識結果"
        assert seg.corrected_text == "認識結果"

        msg = sub.get_nowait()
        assert msg["event"] == "corrected"
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
        """design.md: 全セグメントのテキスト結合"""
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


@patch("src.session_manager.copy_and_paste", new_callable=AsyncMock)
@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestClipboardIntegration:
    async def test_copies_and_pastes_full_text_on_session_end(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_copy_paste: AsyncMock,
    ) -> None:
        """design.md: 全セグメントのテキスト結合 → xclip → xdotool"""
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

        await sm.stop_session()

        mock_copy_paste.assert_called_once_with("こんにちは。お元気ですか。")

    async def test_skips_paste_when_no_segments(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_copy_paste: AsyncMock,
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        await sm.stop_session()

        mock_copy_paste.assert_not_called()

    async def test_session_ends_even_if_paste_fails(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_copy_paste: AsyncMock,
    ) -> None:
        """ペースト失敗時もセッションは正常終了する"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_copy_paste.side_effect = RuntimeError("xclip not found")
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "テスト"})
        await asyncio.sleep(0.05)

        session = await sm.stop_session()

        assert session is not None
        assert session.ended_at is not None
        assert app_state.current_session is None
        assert app_state.recording is False


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestSessionTimeout:
    @patch("src.session_manager.MAX_SESSION_DURATION_SEC", 0.1)
    async def test_auto_stops_after_max_duration(
        self, mock_stt_cls: MagicMock, mock_audio_cls: MagicMock
    ) -> None:
        """design.md: 最大セッション時間: 3分 → 超過時は自動で録音停止"""
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
@patch("src.session_manager.AzureSttClient")
class TestCorrectionIntegration:
    async def test_correction_enabled_connects_gemini(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """design.md: ホットキーA 押下 → Gemini Live API セッション接続(校正ONの場合)"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        app_state.correction_enabled = True
        sm = SessionManager(app_state)

        await sm.start_session()

        mock_correction_cls.assert_called_once()
        mock_correction_cls.return_value.connect.assert_called_once()

        await sm.stop_session()

    async def test_correction_disabled_skips_gemini(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """design.md: 校正OFF → そのまま確定テキストとして表示"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        app_state.correction_enabled = False
        sm = SessionManager(app_state)

        await sm.start_session()

        mock_correction_cls.assert_not_called()

        await sm.stop_session()

    async def test_correction_worker_updates_corrected_text(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """design.md: recognized → Gemini Live API → corrected → ブラウザ (緑)"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_correction_cls.return_value.correct = AsyncMock(
            return_value="校正済みテキスト。"
        )
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "校正済みテキスト"}
        )
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert session.segments[0].corrected_text == "校正済みテキスト。"
        assert session.segments[0].status == "corrected"

        await sm.stop_session()

    async def test_correction_worker_broadcasts_corrected(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_correction_cls.return_value.correct = AsyncMock(return_value="校正済み")
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()
        sub = app_state.broadcaster.subscribe()
        while not sub.empty():
            sub.get_nowait()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "元"})
        await asyncio.sleep(0.05)

        msg = sub.get_nowait()
        assert msg["event"] == "corrected"
        data = json.loads(msg["data"])
        assert data["text"] == "校正済み"

        await sm.stop_session()

    async def test_stop_disconnects_gemini(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """design.md: セッション終了後 → Gemini Live API セッション切断"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        await sm.stop_session()

        mock_correction_cls.return_value.disconnect.assert_called_once()

    @patch("src.session_manager.CORRECTION_TIMEOUT_SEC", 0.1)
    async def test_correction_timeout_falls_back_to_raw_text(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """design.md: タイムアウト → raw_text でペースト"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)

        async def slow_correct(text: str) -> str:
            await asyncio.sleep(10)
            return "never reached"

        mock_correction_cls.return_value.correct = AsyncMock(side_effect=slow_correct)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "元テキスト"}
        )
        await asyncio.sleep(0.05)

        session = await sm.stop_session()

        assert session is not None
        assert session.segments[0].corrected_text == "元テキスト"
        assert session.segments[0].status == "corrected"

    async def test_correction_error_falls_back_to_raw_text(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_correction_cls.return_value.correct = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "元テキスト"}
        )
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert session.segments[0].corrected_text == "元テキスト"
        assert session.segments[0].status == "corrected"

        await sm.stop_session()

    async def test_serial_correction_order(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """design.md: 直列方式
        (1セグメントずつ送信 → turn_complete 待ち → 次セグメント)
        """
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        call_order: list[str] = []

        async def ordered_correct(text: str) -> str:
            call_order.append(text)
            return text + "。"

        mock_correction_cls.return_value.correct = AsyncMock(
            side_effect=ordered_correct
        )
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "1つ目"})
        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "2つ目"})
        await asyncio.sleep(0.05)

        assert call_order == ["1つ目", "2つ目"]
        session = app_state.current_session
        assert session is not None
        assert session.segments[0].corrected_text == "1つ目。"
        assert session.segments[1].corrected_text == "2つ目。"

        await sm.stop_session()


@patch("src.session_manager.save_session")
@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestHistoryIntegration:
    async def test_save_session_called_on_stop(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """design.md: セッション終了時に JSONL に保存"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "テスト"})
        await asyncio.sleep(0.05)

        session = await sm.stop_session()

        mock_save.assert_called_once_with(session)

    async def test_save_not_called_when_not_recording(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        app_state = AppState()
        sm = SessionManager(app_state)

        await sm.stop_session()

        mock_save.assert_not_called()

    async def test_session_ends_even_if_save_fails(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """履歴保存に失敗してもセッションは正常終了する"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_save.side_effect = OSError("disk full")
        app_state = AppState()
        sm = SessionManager(app_state)
        await sm.start_session()

        session = await sm.stop_session()

        assert session is not None
        assert session.ended_at is not None
        assert app_state.recording is False


@patch("src.session_manager.AudioCapture")
@patch("src.session_manager.AzureSttClient")
class TestSessionStartFailure:
    async def test_gemini_failure_falls_back_to_correction_off(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        """Gemini接続失敗時は校正OFFにフォールバックしてセッション続行"""
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_correction_cls.return_value.connect = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        app_state = AppState()
        app_state.correction_enabled = True
        sm = SessionManager(app_state)

        await sm.start_session()

        assert app_state.recording is True
        session = app_state.current_session
        assert session is not None
        assert session.correction_enabled is False

        await sm.stop_session()

    async def test_gemini_failure_broadcasts_error(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
        mock_correction_cls: MagicMock,
    ) -> None:
        _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_correction_cls.return_value.connect = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        app_state = AppState()
        app_state.correction_enabled = True
        sub = app_state.broadcaster.subscribe()
        sm = SessionManager(app_state)

        await sm.start_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        error_msgs = [m for m in messages if m["event"] == "error"]
        assert len(error_msgs) == 1
        assert "校正" in json.loads(error_msgs[0]["data"])["message"]

        await sm.stop_session()

    async def test_stt_failure_aborts_session(
        self,
        mock_stt_cls: MagicMock,
        mock_audio_cls: MagicMock,
    ) -> None:
        """Azure STT開始失敗時はセッションを中止する"""
        mock_stt, _ = _setup_mocks(mock_stt_cls, mock_audio_cls)
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        app_state = AppState()
        app_state.correction_enabled = False
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
        app_state.correction_enabled = False
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
        app_state.correction_enabled = False
        sm = SessionManager(app_state)

        await sm.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None
