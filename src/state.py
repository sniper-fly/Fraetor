from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.sse import SSEBroadcaster

if TYPE_CHECKING:
    from src.models import Segment, Session

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self) -> None:
        self.stt_event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.correction_queue: asyncio.Queue[Segment | None] = asyncio.Queue()
        self.broadcaster: SSEBroadcaster = SSEBroadcaster()
        self.current_session: Session | None = None
        self.correction_enabled: bool = True
        self.recording: bool = False
        self.paste_enabled: bool = False
        self.pending_session: Session | None = None
