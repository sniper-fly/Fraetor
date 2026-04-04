import asyncio

import pytest

from src.sse import SSEBroadcaster


@pytest.fixture
def broadcaster() -> SSEBroadcaster:
    return SSEBroadcaster()


class TestSSEBroadcaster:
    def test_subscribe_adds_queue(self, broadcaster: SSEBroadcaster) -> None:
        queue = broadcaster.subscribe()
        assert queue in broadcaster._subscribers

    def test_unsubscribe_removes_queue(self, broadcaster: SSEBroadcaster) -> None:
        queue = broadcaster.subscribe()
        broadcaster.unsubscribe(queue)
        assert queue not in broadcaster._subscribers

    async def test_broadcast_sends_to_all_subscribers(
        self, broadcaster: SSEBroadcaster
    ) -> None:
        q1 = broadcaster.subscribe()
        q2 = broadcaster.subscribe()

        await broadcaster.broadcast("test_event", {"key": "value"})

        msg1 = await asyncio.wait_for(q1.get(), timeout=1)
        msg2 = await asyncio.wait_for(q2.get(), timeout=1)
        assert msg1 == msg2
        assert msg1["event"] == "test_event"
        assert '"key": "value"' in msg1["data"]

    async def test_broadcast_string_data(self, broadcaster: SSEBroadcaster) -> None:
        queue = broadcaster.subscribe()
        await broadcaster.broadcast("keepalive", "")

        msg = await asyncio.wait_for(queue.get(), timeout=1)
        assert msg["data"] == ""

    async def test_broadcast_no_subscribers_is_noop(
        self, broadcaster: SSEBroadcaster
    ) -> None:
        await broadcaster.broadcast("test", {"data": 1})
