from __future__ import annotations

from src.dictation.application.app_state import AppState
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster


class TestAppState:
    def test_initial_state(self) -> None:
        broadcaster = SSEBroadcaster()
        app_state = AppState(broadcaster=broadcaster)

        assert app_state.broadcaster is broadcaster
        assert app_state.current_session is None
        assert app_state.recording is False
        assert app_state.pending_session is None
        assert app_state.stt_event_queue.empty()
