from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.sse import SSEBroadcaster

if TYPE_CHECKING:
    from src.models import Session

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self) -> None:
        self.hotkey_queue: asyncio.Queue[str] = asyncio.Queue()
        self.stt_event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.correction_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.broadcaster: SSEBroadcaster = SSEBroadcaster()
        self.current_session: Session | None = None
        self.correction_enabled: bool = True
        self.recording: bool = False


async def run_hotkey_handler(app_state: AppState) -> None:
    while True:
        await app_state.hotkey_queue.get()
        app_state.recording = not app_state.recording
        await app_state.broadcaster.broadcast(
            "status", {"recording": app_state.recording}
        )
        logger.info("Recording: %s", app_state.recording)
