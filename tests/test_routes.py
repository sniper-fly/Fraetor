from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from src.app import app
from src.routes import events as events_handler
from src.state import AppState

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


class TestIndex:
    def test_serves_browser_ui(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        # design.md: タブ切替 (メイン/履歴)
        assert "メイン" in html
        assert "履歴" in html
        # design.md: 校正ON/OFFトグル + 録音インジケーター
        assert "校正" in html
        assert "録音" in html
        # design.md: TailwindCSS (CDN)
        assert "tailwindcss" in html


class TestCorrectionToggle:
    def test_default_is_enabled(self, client: TestClient) -> None:
        response = client.get("/api/correction-status")
        assert response.json() == {"correction_enabled": True}

    def test_toggle_cycle(self, client: TestClient) -> None:
        """トグルで ON→OFF→ON と切り替わり、status にも反映される"""
        result = client.post("/api/correction-toggle").json()
        assert result["correction_enabled"] is False
        assert (
            client.get("/api/correction-status").json()["correction_enabled"] is False
        )

        result = client.post("/api/correction-toggle").json()
        assert result["correction_enabled"] is True


class TestHistory:
    def test_returns_empty_when_no_file(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.routes.HISTORY_FILE", tmp_path / "nonexistent.jsonl")
        response = client.get("/api/history")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_empty_for_empty_file(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        monkeypatch.setattr("src.routes.HISTORY_FILE", jsonl)
        assert client.get("/api/history").json() == []

    def test_returns_sessions_newest_first(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """design.md: 新しいセッションが上に表示"""
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text(
            '{"id":"old","started_at":"2026-04-04T14:00:00","text":"古い"}\n'
            '{"id":"new","started_at":"2026-04-04T15:00:00","text":"新しい"}\n'
        )
        monkeypatch.setattr("src.routes.HISTORY_FILE", jsonl)
        sessions = client.get("/api/history").json()
        assert len(sessions) == 2
        assert sessions[0]["id"] == "new"
        assert sessions[1]["id"] == "old"


class TestToggleRecording:
    def test_starts_recording(self, client: TestClient) -> None:
        mock_sm = AsyncMock()
        client.app.state.session_manager = mock_sm  # type: ignore[attr-defined]

        response = client.post("/api/toggle-recording")

        assert response.status_code == 200
        mock_sm.start_session.assert_called_once()

    def test_stops_recording(self, client: TestClient) -> None:
        mock_sm = AsyncMock()
        client.app.state.session_manager = mock_sm  # type: ignore[attr-defined]
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        app_state.recording = True

        response = client.post("/api/toggle-recording")

        assert response.status_code == 200
        mock_sm.stop_session.assert_called_once()

    def test_returns_recording_state(self, client: TestClient) -> None:
        mock_sm = AsyncMock()
        client.app.state.session_manager = mock_sm  # type: ignore[attr-defined]

        response = client.post("/api/toggle-recording")

        assert response.json() == {"recording": False}


class TestEventsSSE:
    async def test_sends_keepalive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """keepalive間隔経過後にkeepaliveイベントが生成される"""
        monkeypatch.setattr("src.routes.SSE_KEEPALIVE_SEC", 0.1)

        app_state = AppState()
        request = MagicMock()
        request.app.state.app_state = app_state

        response = await events_handler(request)

        async def _first_event() -> object:
            async for event in response.body_iterator:
                return event
            return None  # pragma: no cover

        event = await asyncio.wait_for(_first_event(), timeout=2)
        assert event == {"event": "keepalive", "data": ""}
