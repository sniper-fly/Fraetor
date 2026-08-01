from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from starlette.testclient import TestClient


class TestHistory:
    def test_returns_sessions_from_repository(self, client: TestClient) -> None:
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = [
            {"id": "new", "started_at": "2026-04-04T15:00:00", "text": "新しい"},
            {"id": "old", "started_at": "2026-04-04T14:00:00", "text": "古い"},
        ]
        client.app.state.history_repository = mock_repo  # type: ignore[attr-defined]

        response = client.get("/api/history")

        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) == 2
        assert sessions[0]["id"] == "new"
        assert sessions[1]["id"] == "old"

    def test_returns_empty_list(self, client: TestClient) -> None:
        mock_repo = MagicMock()
        mock_repo.list_all.return_value = []
        client.app.state.history_repository = mock_repo  # type: ignore[attr-defined]

        response = client.get("/api/history")

        assert response.json() == []


class TestDeleteHistory:
    def test_delete_existing_session(self, client: TestClient) -> None:
        mock_repo = MagicMock()
        mock_repo.delete.return_value = True
        client.app.state.history_repository = mock_repo  # type: ignore[attr-defined]

        response = client.request("DELETE", "/api/history/aaa")

        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        mock_repo.delete.assert_called_once_with("aaa")

    def test_delete_nonexistent_returns_404(self, client: TestClient) -> None:
        mock_repo = MagicMock()
        mock_repo.delete.return_value = False
        client.app.state.history_repository = mock_repo  # type: ignore[attr-defined]

        response = client.request("DELETE", "/api/history/nonexistent")

        assert response.status_code == 404
