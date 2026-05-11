"""Shared WebSocket side effects for clear-proposal expiry (handlers + maintenance)."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.core.connection_manager import ConnectionManager
from backend.core.room_manager import RoomManager
from backend.handlers.error_handler import ErrorBuilder


async def emit_room_broadcast_after_append(
    *,
    room_manager: RoomManager,
    connection_manager: ConnectionManager,
    room_id: str,
    message: Dict[str, Any],
) -> None:
    await room_manager.append_event(room_id, message)
    await connection_manager.broadcast(room_id, message)


async def emit_pending_clear_proposal_messages(
    *,
    room_manager: RoomManager,
    connection_manager: ConnectionManager,
    room_id: str,
    messages: List[Dict[str, Any]],
) -> None:
    for msg in messages:
        await emit_room_broadcast_after_append(
            room_manager=room_manager,
            connection_manager=connection_manager,
            room_id=room_id,
            message=msg,
        )


async def maybe_emit_expired_clear_proposal_for_room(
    *,
    room_manager: RoomManager,
    connection_manager: ConnectionManager,
    room_id: str,
    now_ms: int,
    error_builder: ErrorBuilder,
) -> None:
    msg = await room_manager.pop_expired_clear_proposal_broadcast_if_any(room_id, now_ms, error_builder)
    if msg is None:
        return
    await emit_room_broadcast_after_append(
        room_manager=room_manager,
        connection_manager=connection_manager,
        room_id=room_id,
        message=msg,
    )
