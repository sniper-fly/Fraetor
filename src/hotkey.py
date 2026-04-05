from __future__ import annotations

import asyncio
import contextlib
import logging

import evdev

from src.config import HOTKEY_RECORD

logger = logging.getLogger(__name__)


class HotkeyListener:
    def __init__(
        self,
        queue: asyncio.Queue[str],
        hotkey: str = HOTKEY_RECORD,
    ) -> None:
        self._queue = queue
        self._hotkey = hotkey
        self._keycode: int = evdev.ecodes.ecodes[hotkey]
        self._tasks: list[asyncio.Task[None]] = []

    def _find_keyboards(
        self,
    ) -> list[evdev.InputDevice]:  # type: ignore[type-arg]
        keyboards: list[evdev.InputDevice] = []  # type: ignore[type-arg]
        permission_denied = 0
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except PermissionError:
                permission_denied += 1
                continue
            except OSError:
                continue
            caps: dict[int, list[int]] = dev.capabilities()
            if (
                evdev.ecodes.EV_KEY in caps
                and self._keycode in caps[evdev.ecodes.EV_KEY]
            ):
                keyboards.append(dev)
            else:
                dev.close()
        if permission_denied > 0 and not keyboards:
            logger.warning(
                "%d 台のデバイスにアクセスできません。"
                "sudo usermod -aG input $USER を実行後、再ログインしてください",
                permission_denied,
            )
        return keyboards

    async def run(self) -> None:
        keyboards = self._find_keyboards()
        if not keyboards:
            logger.warning("No keyboard device with %s found", self._hotkey)
            return
        logger.info("Monitoring %d device(s) for %s", len(keyboards), self._hotkey)
        self._tasks = [asyncio.create_task(self._monitor(dev)) for dev in keyboards]
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._tasks)

    async def _monitor(
        self,
        device: evdev.InputDevice,  # type: ignore[type-arg]
    ) -> None:
        logger.info("Listening on %s (%s)", device.path, device.name)
        try:
            async for event in device.async_read_loop():
                if (
                    event.type == evdev.ecodes.EV_KEY
                    and event.code == self._keycode
                    and event.value == 1
                ):
                    logger.info("Hotkey %s pressed", self._hotkey)
                    await self._queue.put(self._hotkey)
        except OSError:
            logger.exception("Device error: %s", device.path)
        finally:
            device.close()

    def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
