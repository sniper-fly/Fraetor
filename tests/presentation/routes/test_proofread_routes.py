from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from src.dictation.domain.models import Segment
from src.transcript_history.domain.models import FinalizedSession

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from src.dictation.application.app_state import AppState


def _make_pending_session(session_id: str = "pending-session-id") -> FinalizedSession:
    return FinalizedSession(
        id=session_id,
        segments=[Segment(id=0, text="校正済み。")],
        started_at=datetime(2026, 4, 4, 14, 28, 0, tzinfo=UTC),
        ended_at=datetime(2026, 4, 4, 14, 28, 15, tzinfo=UTC),
        timed_out=False,
    )


class TestProofread:
    def test_returns_proofread_text(self, client: TestClient) -> None:
        """校正成功時にLLMの結果が返される。"""
        mock_use_case = AsyncMock()
        mock_use_case.execute.return_value = ("校正済みテキスト", True)
        client.app.state.proofread_text_use_case = mock_use_case  # type: ignore[attr-defined]

        response = client.post("/api/proofread", json={"text": "元のテキスト"})

        assert response.json() == {"text": "校正済みテキスト", "proofread": True}
        mock_use_case.execute.assert_called_once_with("元のテキスト")

    def test_returns_original_on_error(self, client: TestClient) -> None:
        """校正失敗時に元テキストが返される。"""
        mock_use_case = AsyncMock()
        mock_use_case.execute.return_value = ("元のテキスト", False)
        client.app.state.proofread_text_use_case = mock_use_case  # type: ignore[attr-defined]

        response = client.post("/api/proofread", json={"text": "元のテキスト"})

        assert response.json() == {"text": "元のテキスト", "proofread": False}


class TestFinalizeSession:
    def test_calls_use_case_and_clears_pending(self, client: TestClient) -> None:
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        pending = _make_pending_session()
        app_state.add_pending_session(pending)
        mock_use_case = AsyncMock()
        client.app.state.finalize_session_use_case = mock_use_case  # type: ignore[attr-defined]

        response = client.post(
            "/api/finalize-session",
            json={"session_id": pending.id, "text": "edited text"},
        )

        assert response.json() == {"ok": True}
        mock_use_case.execute.assert_called_once_with(pending, text="edited text")
        assert app_state.pending_sessions == []

    def test_returns_false_when_no_pending(self, client: TestClient) -> None:
        mock_use_case = AsyncMock()
        client.app.state.finalize_session_use_case = mock_use_case  # type: ignore[attr-defined]

        response = client.post(
            "/api/finalize-session",
            json={"session_id": "unknown-id", "text": "some text"},
        )
        assert response.json() == {"ok": False}
        mock_use_case.execute.assert_not_called()


class TestFinalizeSessionWithMultiplePending:
    def test_finalizes_only_specified_session_id(self, client: TestClient) -> None:
        """複数セッションが同時に確定待ちの状態でも、指定したsession_idのみが
        確定され、他のpending_sessionsに影響しない (取り違え防止の回帰テスト)。"""
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        first = _make_pending_session("first")
        second = _make_pending_session("second")
        app_state.add_pending_session(first)
        app_state.add_pending_session(second)
        mock_use_case = AsyncMock()
        client.app.state.finalize_session_use_case = mock_use_case  # type: ignore[attr-defined]

        response = client.post(
            "/api/finalize-session",
            json={"session_id": "second", "text": "second text"},
        )

        assert response.json() == {"ok": True}
        mock_use_case.execute.assert_called_once_with(second, text="second text")
        assert [s.id for s in app_state.pending_sessions] == ["first"]
