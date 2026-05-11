"""DRAW message handler."""

from __future__ import annotations

from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType


class DrawHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))

        if not ctx.state_manager.validate_user_action(user_id, MessageType.DRAW):
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

        ctx.state_manager.on_activity(user_id, message_type=MessageType.DRAW)
        user_name = await ctx.room_manager.get_user_display_name(room_id, user_id)
        broadcast = ctx.error_builder.build_broadcast(
            msg_id,
            room_id,
            user_id,
            payload={
                "event_type": BroadcastEventType.DRAW.value,
                "user_id": user_id,
                "user_name": user_name,
                "stroke_id": payload["stroke_id"],
                "tool": payload["tool"],
                "color": payload["color"],
                "width": payload["width"],
                "points": payload["points"],
            },
            now_ms=ctx.now_ms,
        )
        sequence_id = await ctx.room_manager.append_event(room_id, broadcast)
        broadcast["sequence_id"] = sequence_id

        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=sequence_id,
            now_ms=ctx.now_ms,
            payload={
                "status": "ok",
                "op": "draw",
                "stroke_id": payload["stroke_id"],
                "tool": payload["tool"],
                "server_sequence": sequence_id,
            },
        )
        return HandlerResult(
            ack=ack,
            broadcasts=[BroadcastInstruction(room_id=room_id, message=broadcast)],
        )
