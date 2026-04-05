from __future__ import annotations

import asyncio
import json

from src.state import AppState, run_hotkey_handler


class TestRunHotkeyHandler:
    async def test_toggles_recording_on(self) -> None:
        app_state = AppState()
        assert app_state.recording is False

        await app_state.hotkey_queue.put("KEY_F9")

        task = asyncio.create_task(run_hotkey_handler(app_state))
        await asyncio.sleep(0.05)
        task.cancel()

        assert app_state.recording is True

    async def test_toggles_recording_off_after_two_presses(self) -> None:
        app_state = AppState()

        await app_state.hotkey_queue.put("KEY_F9")
        await app_state.hotkey_queue.put("KEY_F9")

        task = asyncio.create_task(run_hotkey_handler(app_state))
        await asyncio.sleep(0.05)
        task.cancel()

        assert app_state.recording is False

    async def test_broadcasts_status_on_toggle(self) -> None:
        app_state = AppState()
        sub_queue = app_state.broadcaster.subscribe()

        await app_state.hotkey_queue.put("KEY_F9")

        task = asyncio.create_task(run_hotkey_handler(app_state))
        await asyncio.sleep(0.05)
        task.cancel()

        msg = sub_queue.get_nowait()
        assert msg["event"] == "status"
        data = json.loads(msg["data"])
        assert data["recording"] is True
