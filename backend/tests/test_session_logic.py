"""Regression tests for room/session exclusivity rules."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from backend.core.models import UserState
from backend.main import _cleanup_disconnected_user
from backend.tests.conftest import FakeWebSocket, build_message, create_backend_stack


def test_user_cannot_join_second_room():
    async def run() -> None:
        stack = create_backend_stack()
        router = stack["router"]
        cm = stack["connection_manager"]
        sm = stack["state_manager"]

        await cm.register("c1", FakeWebSocket())
        sm.on_connected("alice", "c1")
        join_a = build_message(
            "join",
            "alice",
            "room-a",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        )
        first = await router.handle_raw(json.dumps(join_a), connection_id="c1")
        assert first.ack["type"] == "ack"

        await cm.register("c2", FakeWebSocket())
        sm.on_connected("alice", "c2")
        join_b = build_message(
            "join",
            "alice",
            "room-b",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        )
        second = await router.handle_raw(json.dumps(join_b), connection_id="c2")
        assert second.ack["type"] == "error"
        assert second.ack["payload"]["error_code"] == "USER_ALREADY_JOINED"
        existing = await stack["room_manager"].find_room_for_user("alice")
        assert existing == "room-a"

    asyncio.run(run())


def test_duplicate_connection_id_detected():
    async def run() -> None:
        stack = create_backend_stack()
        cm = stack["connection_manager"]
        await cm.register("c1", FakeWebSocket())
        assert await cm.is_connection_id_taken("c1") is True
        assert await cm.is_connection_id_taken("c2") is False

    asyncio.run(run())


def test_duplicate_user_id_indexed():
    async def run() -> None:
        stack = create_backend_stack()
        cm = stack["connection_manager"]
        await cm.register("c1", FakeWebSocket(), user_id="alice")
        await cm.register("c2", FakeWebSocket(), user_id="bob")

        alice_entry = await cm.get_connection_by_user("alice")
        bob_entry = await cm.get_connection_by_user("bob")
        assert alice_entry is not None
        assert alice_entry.connection_id == "c1"
        assert bob_entry is not None
        assert bob_entry.connection_id == "c2"

        await cm.unregister("c1")
        assert await cm.get_connection_by_user("alice") is None
        assert await cm.get_connection_by_user("bob") is not None

    asyncio.run(run())


def test_duplicate_user_id_rejected_in_same_room():
    async def run() -> None:
        stack = create_backend_stack()
        router = stack["router"]
        cm = stack["connection_manager"]
        sm = stack["state_manager"]

        await cm.register("c1", FakeWebSocket())
        sm.on_connected("alice", "c1")
        join_a = build_message(
            "join",
            "alice",
            "room-dup",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        )
        first = await router.handle_raw(json.dumps(join_a), connection_id="c1")
        assert first.ack["type"] == "ack"

        await cm.register("c2", FakeWebSocket())
        sm.on_connected("alice", "c2")
        join_b = build_message(
            "join",
            "alice",
            "room-dup",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice-2", "client_type": "web"}},
        )
        second = await router.handle_raw(json.dumps(join_b), connection_id="c2")
        assert second.ack["type"] == "error"
        assert second.ack["payload"]["error_code"] == "USER_ALREADY_JOINED"
        assert second.ack["payload"]["details"]["reason"] == "duplicate_user_id_in_room"
        assert await cm.find_user_connection_in_room("room-dup", "alice") is not None

    asyncio.run(run())


def test_duplicate_user_name_rejected_in_same_room():
    async def run() -> None:
        stack = create_backend_stack()
        router = stack["router"]
        cm = stack["connection_manager"]
        sm = stack["state_manager"]

        await cm.register("c1", FakeWebSocket())
        sm.on_connected("alice", "c1")
        first = await router.handle_raw(
            json.dumps(
                build_message(
                    "join",
                    "alice",
                    "room-name-dup",
                    {
                        "client_version": "1.0.0",
                        "metadata": {"user_name": "Display-A", "client_type": "web"},
                    },
                )
            ),
            connection_id="c1",
        )
        assert first.ack["type"] == "ack"

        await cm.register("c2", FakeWebSocket())
        sm.on_connected("bob", "c2")
        second = await router.handle_raw(
            json.dumps(
                build_message(
                    "join",
                    "bob",
                    "room-name-dup",
                    {
                        "client_version": "1.0.0",
                        "metadata": {"user_name": "display-a", "client_type": "web"},
                    },
                )
            ),
            connection_id="c2",
        )
        assert second.ack["type"] == "error"
        assert second.ack["payload"]["error_code"] == "USER_ALREADY_JOINED"
        assert second.ack["payload"]["details"]["reason"] == "duplicate_user_name_in_room"

    asyncio.run(run())


def test_disconnect_cleanup_runs_on_leave_before_room_leave():
    async def run() -> None:
        stack = create_backend_stack()
        cm = stack["connection_manager"]
        rm = stack["room_manager"]
        sm = stack["state_manager"]
        error_builder = stack["error_builder"]

        await cm.register("c1", FakeWebSocket(), user_id="alice", room_id="room-a")
        sm.on_connected("alice", "c1")
        sm.on_join("alice", "room-a")
        await rm.join("room-a", "alice", metadata={"user_name": "Alice"})
        assert sm.get_user_state("alice") == UserState.JOINED

        app = SimpleNamespace(
            state=SimpleNamespace(
                room_manager=rm,
                connection_manager=cm,
                state_manager=sm,
                error_builder=error_builder,
            )
        )
        await _cleanup_disconnected_user(app, "alice", "room-a", "disconnect")
        assert sm.get_user_state("alice") == UserState.LEFT
        assert await rm.is_user_in_room("room-a", "alice") is False

    asyncio.run(run())
