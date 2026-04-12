from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from src.app import app
from src.models import Segment, Session
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
        assert "メイン" in html
        assert "履歴" in html
        assert "録音" in html
        assert "ペースト" in html
        assert "tailwindcss" in html


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
        """azure-stt-only-spec.md: 新しいセッションが上に表示"""
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


class TestPasteToggle:
    def test_default_is_off(self, client: TestClient) -> None:
        response = client.get("/api/paste-status")
        assert response.json() == {"paste_enabled": False}

    def test_toggle_cycle(self, client: TestClient) -> None:
        """トグルで OFF->ON->OFF と切り替わり、status にも反映される"""
        result = client.post("/api/paste-toggle").json()
        assert result["paste_enabled"] is True
        assert client.get("/api/paste-status").json()["paste_enabled"] is True

        result = client.post("/api/paste-toggle").json()
        assert result["paste_enabled"] is False


class TestPasteStatus:
    def test_returns_current_setting(self, client: TestClient) -> None:
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        app_state.paste_enabled = True
        assert client.get("/api/paste-status").json() == {"paste_enabled": True}


def _make_pending_session() -> Session:
    return Session(
        id="pending-session-id",
        segments=[
            Segment(id=0, text="校正済み。"),
        ],
        started_at=datetime(2026, 4, 4, 14, 28, 0, tzinfo=UTC),
        ended_at=datetime(2026, 4, 4, 14, 28, 15, tzinfo=UTC),
    )


class TestFinalizeSession:
    @patch("src.routes.save_session")
    @patch("src.routes.copy_to_clipboard", new_callable=AsyncMock)
    def test_copies_and_saves_when_pending(
        self,
        mock_copy: AsyncMock,
        mock_save: MagicMock,
        client: TestClient,
    ) -> None:
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        pending = _make_pending_session()
        app_state.pending_session = pending

        response = client.post(
            "/api/finalize-session",
            json={"text": "edited text"},
        )

        assert response.json() == {"ok": True}
        mock_copy.assert_called_once_with("edited text")
        mock_save.assert_called_once_with(pending, text_override="edited text")
        assert app_state.pending_session is None

    def test_returns_false_when_no_pending(self, client: TestClient) -> None:
        response = client.post(
            "/api/finalize-session",
            json={"text": "some text"},
        )
        assert response.json() == {"ok": False}
