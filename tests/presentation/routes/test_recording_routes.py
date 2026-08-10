from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from src.presentation.routes.recording_routes import events as events_handler
from src.shared.config.dynamic_settings import DynamicSettings
from tests.fakes import InMemorySettingsRepository

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
        """keepalive間隔経過後にkeepaliveイベントが生成される。

        `sse_keepalive_sec` は秒単位の int なので最短の1秒を使う。
        """
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        request = MagicMock()
        request.app.state.app_state = app_state
        request.app.state.settings_repository = InMemorySettingsRepository(
            DynamicSettings(sse_keepalive_sec=1)
        )

        response = await events_handler(request)

        async def _first_event() -> object:
            async for event in response.body_iterator:
                return event
            return None  # pragma: no cover

        event = await asyncio.wait_for(_first_event(), timeout=3)
        assert event == {"event": "keepalive", "data": ""}
