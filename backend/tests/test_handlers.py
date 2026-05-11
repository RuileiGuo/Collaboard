from __future__ import annotations

import asyncio
import json

from backend.core.connection_manager import ConnectionManager
from backend.core.message_router import MessageRouter, RouterConfig
from backend.core.room_manager import RoomManager
from backend.core.state_manager import StateManager
from backend.core.schemas import validate_client_message
from backend.handlers.annotation_delete_handler import AnnotationDeleteHandler
from backend.handlers.annotation_handler import AnnotationHandler
from backend.handlers.annotation_restore_handler import AnnotationRestoreHandler
from backend.handlers.clear_handler import ClearHandler
from backend.handlers.clear_propose_handler import ClearProposeHandler
from backend.handlers.clear_vote_handler import ClearVoteHandler
from backend.handlers.draw_handler import DrawHandler
from backend.handlers.draw_redo_handler import DrawRedoHandler
from backend.handlers.draw_undo_handler import DrawUndoHandler
from backend.handlers.error_handler import ErrorBuilder
from backend.handlers.join_handler import JoinHandler
from backend.handlers.leave_handler import LeaveHandler
from backend.handlers.state_sync_handler import StateSyncHandler
from backend.tests.conftest import FakeWebSocket, build_message, create_backend_stack


def _build_router(stack, *, rate_capacity: int = 100, rate_refill: float = 100.0) -> MessageRouter:
    return MessageRouter(
        handlers={
            "join": JoinHandler(),
            "leave": LeaveHandler(),
            "draw": DrawHandler(),
            "draw_undo": DrawUndoHandler(),
            "draw_redo": DrawRedoHandler(),
            "annotation": AnnotationHandler(),
            "annotation_delete": AnnotationDeleteHandler(),
            "annotation_restore": AnnotationRestoreHandler(),
            "clear": ClearHandler(),
            "clear_propose": ClearProposeHandler(),
            "clear_vote": ClearVoteHandler(),
            "state_sync": StateSyncHandler(),
        },
        connection_manager=stack["connection_manager"],
        room_manager=stack["room_manager"],
        state_manager=stack["state_manager"],
        schema_validator=validate_client_message,
        error_builder=ErrorBuilder(),
        config=RouterConfig(rate_capacity=rate_capacity, rate_refill_per_sec=rate_refill),
    )


def test_join_then_draw_and_dedup():
    async def run() -> None:
        backend_stack = create_backend_stack()
        router = _build_router(backend_stack)
        ws = FakeWebSocket()
        await backend_stack["connection_manager"].register("c1", ws)
        backend_stack["state_manager"].on_connected("alice", "c1")

        join_message = build_message(
            "join",
            "alice",
            "room-a",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        )
        join_result = await router.handle_raw(json.dumps(join_message), connection_id="c1")
        assert join_result.ack["type"] == "ack"
        assert join_result.broadcasts[0].exclude_user_id == "alice"

        draw_message = build_message(
            "draw",
            "alice",
            "room-a",
            {
                "stroke_id": "550e8400-e29b-41d4-a716-446655440001",
                "tool": "pen",
                "color": "#FF0000",
                "width": 2,
                "points": [{"x": 1, "y": 2, "pressure": 1.0}],
            },
        )
        draw_result = await router.handle_raw(json.dumps(draw_message), connection_id="c1")
        replay_result = await router.handle_raw(json.dumps(draw_message), connection_id="c1")
        assert draw_result.ack == replay_result.ack
        assert replay_result.broadcasts == []

    asyncio.run(run())


def test_draw_before_join_is_rejected():
    async def run() -> None:
        backend_stack = create_backend_stack()
        router = _build_router(backend_stack)
        await backend_stack["connection_manager"].register("c1", FakeWebSocket())
        backend_stack["state_manager"].on_connected("alice", "c1")
        draw_message = build_message(
            "draw",
            "alice",
            "room-a",
            {
                "stroke_id": "550e8400-e29b-41d4-a716-446655440001",
                "tool": "pen",
                "color": "#FF0000",
                "width": 2,
                "points": [{"x": 1, "y": 2, "pressure": 1.0}],
            },
        )
        result = await router.handle_raw(json.dumps(draw_message), connection_id="c1")
        assert result.ack["type"] == "error"
        assert result.ack["payload"]["error_code"] == "UNAUTHORIZED"

    asyncio.run(run())


def test_rate_limit_returns_error():
    async def run() -> None:
        backend_stack = create_backend_stack()
        router = _build_router(backend_stack, rate_capacity=1, rate_refill=0.0)
        await backend_stack["connection_manager"].register("c1", FakeWebSocket())
        backend_stack["state_manager"].on_connected("alice", "c1")

        join_message = build_message(
            "join",
            "alice",
            "room-a",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        )
        state_sync_message = build_message(
            "state_sync",
            "alice",
            "room-a",
            {"last_received_sequence": -1},
        )

        await router.handle_raw(json.dumps(join_message), connection_id="c1")
        result = await router.handle_raw(json.dumps(state_sync_message), connection_id="c1")
        assert result.ack["payload"]["error_code"] == "RATE_LIMIT"

    asyncio.run(run())


def test_room_event_rate_limit_via_router_after_join():
    """Protocol §9.2: room-level event cap; join consumes one broadcast slot before draw."""

    async def run() -> None:
        connection_manager = ConnectionManager()
        room_manager = RoomManager(room_event_rate_capacity=1, room_event_rate_refill_per_sec=0.0)
        state_manager = StateManager()
        router = MessageRouter(
            handlers={
                "join": JoinHandler(),
                "leave": LeaveHandler(),
                "draw": DrawHandler(),
                "clear": ClearHandler(),
                "state_sync": StateSyncHandler(),
            },
            connection_manager=connection_manager,
            room_manager=room_manager,
            state_manager=state_manager,
            schema_validator=validate_client_message,
            error_builder=ErrorBuilder(),
            config=RouterConfig(),
        )
        await connection_manager.register("c1", FakeWebSocket())
        state_manager.on_connected("alice", "c1")
        join_message = build_message(
            "join",
            "alice",
            "room-rl",
            {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        )
        join_result = await router.handle_raw(json.dumps(join_message), connection_id="c1")
        assert join_result.ack["type"] == "ack"
        draw_message = build_message(
            "draw",
            "alice",
            "room-rl",
            {
                "stroke_id": "550e8400-e29b-41d4-a716-446655440099",
                "tool": "pen",
                "color": "#FF0000",
                "width": 2,
                "points": [{"x": 1, "y": 2, "pressure": 1.0}],
            },
        )
        draw_result = await router.handle_raw(json.dumps(draw_message), connection_id="c1")
        assert draw_result.ack["type"] == "error"
        assert draw_result.ack["payload"]["error_code"] == "RATE_LIMIT"

    asyncio.run(run())
