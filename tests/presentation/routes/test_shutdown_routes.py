from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from src.dictation.application.app_state import AppState
from src.dictation.application.segment_accumulator import SegmentAccumulator
from src.dictation.application.transcription_queue import TranscriptionQueue
from src.dictation.domain.models import RecordingSession, TranscriptionJob
from src.dictation.domain.ports import SttCapabilities, SttEnginePort
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster
from src.presentation.routes.shutdown_routes import shutdown as shutdown_handler
from src.shared.config.dynamic_settings import DynamicSettings
from tests.fakes import InMemorySettingsRepository

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from src.shared.config.ports import SettingsRepositoryPort


class TestShutdown:
    def test_shutdown_returns_ok(self, client: TestClient) -> None:
        client.app.state.shutdowner = MagicMock()  # type: ignore[attr-defined]

        response = client.post("/api/shutdown")

        assert response.json() == {"ok": True}

    def test_shutdown_stops_recording_if_active(self, client: TestClient) -> None:
        client.app.state.shutdowner = MagicMock()  # type: ignore[attr-defined]
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        app_state.recording = True

        response = client.post("/api/shutdown")

        assert response.status_code == 200
        mock_service.stop_session.assert_called_once()

    def test_shutdown_skips_stop_when_not_recording(self, client: TestClient) -> None:
        client.app.state.shutdowner = MagicMock()  # type: ignore[attr-defined]
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]

        response = client.post("/api/shutdown")

        assert response.status_code == 200
        mock_service.stop_session.assert_not_called()

    def test_shutdown_schedules_process_exit(self, client: TestClient) -> None:
        mock_shutdowner = MagicMock()
        client.app.state.shutdowner = mock_shutdowner  # type: ignore[attr-defined]
        repo: SettingsRepositoryPort = client.app.state.settings_repository  # type: ignore[attr-defined]

        client.post("/api/shutdown")

        mock_shutdowner.schedule.assert_called_once_with(repo.get().shutdown_delay_sec)

    def test_shutdown_reads_delay_at_request_time(self, client: TestClient) -> None:
        """設定を更新した直後の shutdown に新しい猶予時間が使われる。"""
        mock_shutdowner = MagicMock()
        client.app.state.shutdowner = mock_shutdowner  # type: ignore[attr-defined]
        repo: SettingsRepositoryPort = client.app.state.settings_repository  # type: ignore[attr-defined]
        repo.update(DynamicSettings(shutdown_delay_sec=2.5))

        client.post("/api/shutdown")

        mock_shutdowner.schedule.assert_called_once_with(2.5)


class TestShutdownWaitsForTranscriptionQueue:
    async def test_session_end_broadcasts_before_shutdown_when_job_pending(
        self,
    ) -> None:
        """キューに処理中のジョブがある状態でshutdownしても、
        session_end (履歴保存の前提) がshutdownより先に配信される。

        TestClientは別スレッド/別イベントループでアプリを実行するため、
        transcription_queue の内部Queueとテストのイベントループが異なると
        クロスループエラーになる。ここでは同一イベントループ上で
        AppState/TranscriptionQueue を直接組み立て、ハンドラを直接呼ぶ。
        """
        broadcaster = SSEBroadcaster()
        app_state = AppState(broadcaster=broadcaster)
        accumulator = SegmentAccumulator(broadcaster)
        transcription_queue = TranscriptionQueue(app_state, accumulator)
        transcription_queue.start()
        sub = broadcaster.subscribe()

        mock_stt = MagicMock(spec=SttEnginePort)

        async def slow_stop() -> None:
            await asyncio.sleep(0.1)

        mock_stt.stop = slow_stop
        mock_stt.capabilities = SttCapabilities(streaming=False, post_processing=True)
        session = RecordingSession(
            id="pending-session", segments=[], started_at=datetime.now(tz=UTC)
        )
        job = TranscriptionJob(
            session=session,
            stt_client=mock_stt,
            event_queue=asyncio.Queue(),
            timed_out=False,
        )
        await transcription_queue.enqueue(job)

        request = MagicMock()
        request.app.state.app_state = app_state
        request.app.state.recording_session_service = AsyncMock()
        request.app.state.transcription_queue = transcription_queue
        request.app.state.shutdowner = MagicMock()
        request.app.state.settings_repository = InMemorySettingsRepository(
            DynamicSettings(mai_timeout_sec=1)
        )

        response = await shutdown_handler(request)

        assert response == {"ok": True}
        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        events = [m["event"] for m in messages]
        assert "session_end" in events
        assert "shutdown" in events
        assert events.index("session_end") < events.index("shutdown")

        await transcription_queue.shutdown(timeout=1)
