from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from src.dictation.application.app_state import AppState


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

        client.post("/api/shutdown")

        mock_shutdowner.schedule.assert_called_once_with(
            client.app.state.shutdown_delay_sec  # type: ignore[attr-defined]
        )
