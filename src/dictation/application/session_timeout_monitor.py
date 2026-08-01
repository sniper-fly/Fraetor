from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class SessionTimeoutMonitor:
    """最大セッション時間、または発話終了からの無音タイムアウトで自動停止する。"""

    def __init__(
        self,
        *,
        max_duration_sec: float,
        silence_timeout_sec: float,
        last_speech_time_fn: Callable[[], float],
        on_timeout: Callable[[], Awaitable[None]],
    ) -> None:
        self._max_duration_sec = max_duration_sec
        self._silence_timeout_sec = silence_timeout_sec
        self._last_speech_time_fn = last_speech_time_fn
        self._on_timeout = on_timeout
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._task and self._task is not asyncio.current_task():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _watch(self) -> None:
        session_start = time.monotonic()
        while True:
            now = time.monotonic()
            remaining_max = session_start + self._max_duration_sec - now
            last_speech = self._last_speech_time_fn()
            remaining_silence = last_speech + self._silence_timeout_sec - now
            remaining = min(remaining_max, remaining_silence)
            if remaining <= 0:
                reason = (
                    "max duration" if remaining_max <= remaining_silence else "silence"
                )
                logger.info(
                    "Session timed out (%s) after %.0f seconds",
                    reason,
                    now - session_start,
                )
                await self._on_timeout()
                return
            await asyncio.sleep(remaining)
