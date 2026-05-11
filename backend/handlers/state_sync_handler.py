"""STATE_SYNC message handler."""

from __future__ import annotations

from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import ErrorCode, MessageType


class StateSyncHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))
        last_received_sequence = int(payload.get("last_received_sequence", -1))

        if not ctx.state_manager.validate_user_action(user_id, MessageType.STATE_SYNC):
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.UNAUTHORIZED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                )
            )

        if not await ctx.room_manager.is_user_in_room(room_id, user_id):
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ROOM_NOT_FOUND,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                )
            )

        ctx.state_manager.on_activity(user_id, message_type=MessageType.STATE_SYNC)
        snapshot = await ctx.room_manager.get_snapshot(room_id)
        events = await ctx.room_manager.get_events_since(room_id, last_received_sequence)
        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=None,
            now_ms=ctx.now_ms,
            payload={
                "status": "ok",
                "room_state": {
                    "room_id": room_id,
                    "current_sequence": snapshot["current_sequence"],
                    "canvas_events": events,
                    "active_users": snapshot["active_users"],
                },
            },
        )
        return HandlerResult(ack=ack)
