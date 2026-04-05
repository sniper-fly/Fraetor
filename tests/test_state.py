from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.state import AppState, run_hotkey_handler


class TestRunHotkeyHandler:
    async def test_calls_start_session_when_not_recording(self) -> None:
        app_state = AppState()
        session_manager = AsyncMock()
        await app_state.hotkey_queue.put("KEY_F9")

        task = asyncio.create_task(run_hotkey_handler(app_state, session_manager))
        await asyncio.sleep(0.05)
        task.cancel()

        session_manager.start_session.assert_called_once()
        session_manager.stop_session.assert_not_called()

    async def test_calls_stop_session_when_recording(self) -> None:
        app_state = AppState()
        app_state.recording = True
        session_manager = AsyncMock()
        await app_state.hotkey_queue.put("KEY_F9")

        task = asyncio.create_task(run_hotkey_handler(app_state, session_manager))
        await asyncio.sleep(0.05)
        task.cancel()

        session_manager.stop_session.assert_called_once()
        session_manager.start_session.assert_not_called()
