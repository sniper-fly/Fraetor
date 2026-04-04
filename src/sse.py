import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SSEBroadcaster:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, str]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, str]]:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self._subscribers.append(queue)
        logger.info("SSE subscriber added (total: %d)", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, str]]) -> None:
        self._subscribers.remove(queue)
        logger.info("SSE subscriber removed (total: %d)", len(self._subscribers))

    async def broadcast(self, event: str, data: Any) -> None:
        message = {
            "event": event,
            "data": json.dumps(data, ensure_ascii=False)
            if not isinstance(data, str)
            else data,
        }
        for queue in self._subscribers:
            await queue.put(message)
