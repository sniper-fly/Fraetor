from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from src.shared.herdr.ports import HerdrClientPort, HerdrSessionInfo

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from src.dictation.application.app_state import AppState


_DEFAULT_FOCUSED_PANE = HerdrSessionInfo(pane_id="w1:p1", label="Claude Code")


class FakeHerdrClient(HerdrClientPort):
    def __init__(
        self,
        *,
        focused_pane: HerdrSessionInfo | None = _DEFAULT_FOCUSED_PANE,
        sessions: list[HerdrSessionInfo] | None = None,
        send_text_result: bool = True,
    ) -> None:
        self.focused_pane = focused_pane
        self.sessions = sessions if sessions is not None else []
        self.send_text_result = send_text_result
        self.sent: list[tuple[str, str]] = []

    async def get_focused_pane(self) -> HerdrSessionInfo | None:
        return self.focused_pane

    async def list_sessions(self) -> list[HerdrSessionInfo]:
        return self.sessions

    async def send_text(self, pane_id: str, text: str) -> bool:
        self.sent.append((pane_id, text))
        return self.send_text_result


class TestToggleRecordingAndSendToHerdr:
    def test_starts_recording_with_focused_pane(self, client: TestClient) -> None:
        fake_herdr = FakeHerdrClient(
            focused_pane=HerdrSessionInfo(pane_id="w1:p1", label="Claude Code")
        )
        client.app.state.herdr_client = fake_herdr  # type: ignore[attr-defined]
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]

        response = client.post("/api/toggle-recording-and-send-to-herdr")

        assert response.json() == {
            "recording": True,
            "target_pane_id": "w1:p1",
            "target_pane_label": "Claude Code",
        }
        mock_service.start_session.assert_called_once_with(
            target_pane_id="w1:p1",
            target_pane_label="Claude Code",
            herdr_requested=True,
        )

    def test_starts_recording_even_when_focused_pane_unavailable(
        self, client: TestClient
    ) -> None:
        fake_herdr = FakeHerdrClient(focused_pane=None)
        client.app.state.herdr_client = fake_herdr  # type: ignore[attr-defined]
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]

        response = client.post("/api/toggle-recording-and-send-to-herdr")

        assert response.json() == {
            "recording": True,
            "target_pane_id": None,
            "target_pane_label": None,
        }
        mock_service.start_session.assert_called_once_with(
            target_pane_id=None, target_pane_label=None, herdr_requested=True
        )

    def test_stops_recording_and_confirms_send(self, client: TestClient) -> None:
        fake_herdr = FakeHerdrClient()
        client.app.state.herdr_client = fake_herdr  # type: ignore[attr-defined]
        mock_service = AsyncMock()
        client.app.state.recording_session_service = mock_service  # type: ignore[attr-defined]
        app_state: AppState = client.app.state.app_state  # type: ignore[attr-defined]
        app_state.recording = True

        response = client.post("/api/toggle-recording-and-send-to-herdr")

        assert response.json() == {"recording": False}
        mock_service.stop_session.assert_called_once_with(herdr_send_confirmed=True)


class TestListHerdrSessions:
    def test_returns_sessions_as_json(self, client: TestClient) -> None:
        fake_herdr = FakeHerdrClient(
            sessions=[
                HerdrSessionInfo(pane_id="w1:p1", label="claude-code"),
                HerdrSessionInfo(pane_id="w1:p2", label="shell"),
            ]
        )
        client.app.state.herdr_client = fake_herdr  # type: ignore[attr-defined]

        response = client.get("/api/herdr-sessions")

        assert response.json() == [
            {"pane_id": "w1:p1", "label": "claude-code"},
            {"pane_id": "w1:p2", "label": "shell"},
        ]


class TestSendToHerdr:
    def test_returns_success_true(self, client: TestClient) -> None:
        fake_herdr = FakeHerdrClient(send_text_result=True)
        client.app.state.herdr_client = fake_herdr  # type: ignore[attr-defined]

        response = client.post(
            "/api/send-to-herdr", json={"pane_id": "w1:p1", "text": "hello"}
        )

        assert response.json() == {"success": True}
        assert fake_herdr.sent == [("w1:p1", "hello")]

    def test_returns_success_false_on_failure(self, client: TestClient) -> None:
        fake_herdr = FakeHerdrClient(send_text_result=False)
        client.app.state.herdr_client = fake_herdr  # type: ignore[attr-defined]

        response = client.post(
            "/api/send-to-herdr", json={"pane_id": "w1:p1", "text": "hello"}
        )

        assert response.json() == {"success": False}
