from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from src.presentation.routes.recording_routes import events as events_handler

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from src.dictation.application.app_state import AppState


class TestToggleRecording:
    def test_starts_recording(self, client: TestClient) -> None:
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]

        response = client.post("/api/toggle-recording")

        assert response.status_code == 200
        mock_service.start_session.assert_called_once()

    def test_stops_recording(self, client: TestClient) -> None:
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        app_state.recording = True

        response = client.post("/api/toggle-recording")

        assert response.status_code == 200
        mock_service.stop_session.assert_called_once()

    def test_returns_recording_state(self, client: TestClient) -> None:
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]

        response = client.post("/api/toggle-recording")

        assert response.json() == {"recording": False}


class TestEventsSSE:
    async def test_sends_keepalive(self, client: TestClient) -> None:
        """keepalive間隔経過後にkeepaliveイベントが生成される"""
        client.app.state.sse_keepalive_sec = 0.1  # type: ignore[attr-defined]

        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        request = MagicMock()
        request.app.state.app_state = app_state
        request.app.state.sse_keepalive_sec = 0.1

        response = await events_handler(request)

        async def _first_event() -> object:
            async for event in response.body_iterator:
                return event
            return None  # pragma: no cover

        event = await asyncio.wait_for(_first_event(), timeout=2)
        assert event == {"event": "keepalive", "data": ""}
