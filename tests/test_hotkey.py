from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import evdev

from src.hotkey import HotkeyListener

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import pytest


class TestFindKeyboards:
    def test_finds_device_with_hotkey(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dev = MagicMock()
        mock_dev.capabilities.return_value = {
            evdev.ecodes.EV_KEY: [evdev.ecodes.KEY_F9]
        }
        monkeypatch.setattr(evdev, "list_devices", lambda: ["/dev/input/event0"])
        monkeypatch.setattr(evdev, "InputDevice", lambda _path: mock_dev)

        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)
        keyboards = listener._find_keyboards()

        assert len(keyboards) == 1
        assert keyboards[0] is mock_dev

    def test_skips_device_without_hotkey(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dev = MagicMock()
        mock_dev.capabilities.return_value = {evdev.ecodes.EV_KEY: [evdev.ecodes.KEY_A]}
        monkeypatch.setattr(evdev, "list_devices", lambda: ["/dev/input/event0"])
        monkeypatch.setattr(evdev, "InputDevice", lambda _path: mock_dev)

        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)
        keyboards = listener._find_keyboards()

        assert len(keyboards) == 0
        mock_dev.close.assert_called_once()

    def test_skips_device_without_ev_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dev = MagicMock()
        mock_dev.capabilities.return_value = {evdev.ecodes.EV_REL: [0, 1]}
        monkeypatch.setattr(evdev, "list_devices", lambda: ["/dev/input/event0"])
        monkeypatch.setattr(evdev, "InputDevice", lambda _path: mock_dev)

        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)
        keyboards = listener._find_keyboards()

        assert len(keyboards) == 0
        mock_dev.close.assert_called_once()

    def test_empty_device_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(evdev, "list_devices", lambda: [])

        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)
        keyboards = listener._find_keyboards()

        assert len(keyboards) == 0

    def test_skips_inaccessible_device(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_os_error(_path: str) -> None:
            raise OSError("Permission denied")

        monkeypatch.setattr(evdev, "list_devices", lambda: ["/dev/input/event0"])
        monkeypatch.setattr(evdev, "InputDevice", raise_os_error)

        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)
        keyboards = listener._find_keyboards()

        assert len(keyboards) == 0


class TestMonitor:
    async def test_enqueues_on_keypress(self) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)

        mock_event = MagicMock()
        mock_event.type = evdev.ecodes.EV_KEY
        mock_event.code = evdev.ecodes.KEY_F9
        mock_event.value = 1

        mock_device = MagicMock()
        mock_device.path = "/dev/input/event0"
        mock_device.name = "Test"

        async def mock_read_loop() -> AsyncGenerator[MagicMock]:
            yield mock_event

        mock_device.async_read_loop = mock_read_loop

        await listener._monitor(mock_device)

        assert queue.get_nowait() == "KEY_F9"
        mock_device.close.assert_called_once()

    async def test_ignores_key_release(self) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)

        mock_event = MagicMock()
        mock_event.type = evdev.ecodes.EV_KEY
        mock_event.code = evdev.ecodes.KEY_F9
        mock_event.value = 0  # release

        mock_device = MagicMock()
        mock_device.path = "/dev/input/event0"
        mock_device.name = "Test"

        async def mock_read_loop() -> AsyncGenerator[MagicMock]:
            yield mock_event

        mock_device.async_read_loop = mock_read_loop

        await listener._monitor(mock_device)

        assert queue.empty()

    async def test_ignores_other_keys(self) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)

        mock_event = MagicMock()
        mock_event.type = evdev.ecodes.EV_KEY
        mock_event.code = evdev.ecodes.KEY_A
        mock_event.value = 1

        mock_device = MagicMock()
        mock_device.path = "/dev/input/event0"
        mock_device.name = "Test"

        async def mock_read_loop() -> AsyncGenerator[MagicMock]:
            yield mock_event

        mock_device.async_read_loop = mock_read_loop

        await listener._monitor(mock_device)

        assert queue.empty()


class TestRun:
    async def test_no_devices_returns_without_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(evdev, "list_devices", lambda: [])

        queue: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(queue)
        await listener.run()
