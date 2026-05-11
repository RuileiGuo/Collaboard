from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.core.models import BroadcastEventType
from backend.core.room_manager import RoomManager
from backend.tests.conftest import FakeWebSocket, create_backend_stack
from backend.utils.exceptions import RoomEventRateLimitError


def test_connection_manager_broadcast_excludes_user():
    async def run() -> None:
        backend_stack = create_backend_stack()
        manager = backend_stack["connection_manager"]
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        await manager.register("c1", ws1, user_id="alice", room_id="room-a")
        await manager.register("c2", ws2, user_id="bob", room_id="room-a")

        delivered = await manager.broadcast("room-a", {"type": "broadcast"}, exclude_user_id="alice")
        assert delivered == 1
        assert ws1.sent == []
        assert ws2.sent[0]["type"] == "broadcast"

    asyncio.run(run())


def test_room_manager_join_leave_and_ttl_expire():
    async def run() -> None:
        backend_stack = create_backend_stack()
        manager = backend_stack["room_manager"]
        room = await manager.join("room-a", "alice", metadata={"user_name": "Alice"})
        assert room.state.value == "active"

        room = await manager.leave("room-a", "alice")
        assert room.state.value == "idle"

        expired = await manager.expire_rooms(now=room.idle_deadline + 1)
        assert "room-a" in expired
        assert await manager.get("room-a") is None

    asyncio.run(run())


def test_room_append_event_hits_room_rate_limit():
    async def run() -> None:
        rm = RoomManager(room_event_rate_capacity=2, room_event_rate_refill_per_sec=0.0)
        await rm.join("room-rl", "alice", metadata={})

        def stub_draw() -> dict:
            return {
                "msg_id": str(uuid.uuid4()),
                "type": "broadcast",
                "timestamp": 0,
                "user_id": "alice",
                "room_id": "room-rl",
                "sequence_id": None,
                "payload": {"event_type": BroadcastEventType.DRAW.value},
            }

        await rm.append_event("room-rl", stub_draw())
        await rm.append_event("room-rl", stub_draw())
        with pytest.raises(RoomEventRateLimitError):
            await rm.append_event("room-rl", stub_draw())

    asyncio.run(run())


def test_connection_send_failure_unregisters_connection():
    async def run() -> None:
        backend_stack = create_backend_stack()
        manager = backend_stack["connection_manager"]
        ws = FakeWebSocket(fail_send=True)
        await manager.register("c1", ws, user_id="alice", room_id="room-a")
        sent = await manager.send("c1", {"type": "ack"})
        assert sent is False
        assert await manager.get_connection("c1") is None

    asyncio.run(run())
