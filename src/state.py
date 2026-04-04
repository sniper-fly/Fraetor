from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.sse import SSEBroadcaster

if TYPE_CHECKING:
    from src.models import Session


class AppState:
    def __init__(self) -> None:
        self.hotkey_queue: asyncio.Queue[str] = asyncio.Queue()
        self.stt_event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.correction_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.broadcaster: SSEBroadcaster = SSEBroadcaster()
        self.current_session: Session | None = None
        self.correction_enabled: bool = True
        self.recording: bool = False
