"""LEAVE message handler."""

from __future__ import annotations

from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType
from backend.handlers.proposal_side_effects import emit_pending_clear_proposal_messages


class LeaveHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))

        if not ctx.state_manager.validate_user_action(user_id, MessageType.LEAVE):
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.UNAUTHORIZED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"user_id": user_id},
                )
            )

        room = await ctx.room_manager.get(room_id)
        if room is None:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ROOM_NOT_FOUND,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                )
            )

        if not await ctx.room_manager.is_user_in_room(room_id, user_id):
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.UNAUTHORIZED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"user_id": user_id},
                )
            )

        user_name = await ctx.room_manager.get_user_display_name(room_id, user_id)

        proposal_msgs = await ctx.room_manager.collect_clear_proposal_messages_on_user_exit(
            room_id, user_id, ctx.error_builder, ctx.now_ms
        )
        await emit_pending_clear_proposal_messages(
            room_manager=ctx.room_manager,
            connection_manager=ctx.connection_manager,
            room_id=room_id,
            messages=proposal_msgs,
        )

        ctx.state_manager.on_leave(user_id)
        room = await ctx.room_manager.leave(room_id, user_id)
        broadcasts = []

        user_left = ctx.error_builder.build_broadcast(
            msg_id,
            room_id,
            user_id,
            payload={
                "event_type": BroadcastEventType.USER_LEFT.value,
                "user_id": user_id,
                "user_name": user_name,
                "reason": payload.get("reason", "manual"),
                "remaining_users": len(room.users),
            },
            now_ms=ctx.now_ms,
        )
        user_left["sequence_id"] = await ctx.room_manager.append_event(room_id, user_left)
        broadcasts.append(
            BroadcastInstruction(room_id=room_id, message=user_left, exclude_user_id=user_id)
        )

        if len(room.users) == 0:
            room_idle = ctx.error_builder.build_broadcast(
                msg_id,
                room_id,
                "server",
                payload={
                    "event_type": BroadcastEventType.ROOM_IDLE.value,
                    "room_id": room_id,
                    "ttl_seconds": 60,
                },
                now_ms=ctx.now_ms,
            )
            room_idle["sequence_id"] = await ctx.room_manager.append_event(room_id, room_idle)
            broadcasts.append(BroadcastInstruction(room_id=room_id, message=room_idle))

        snapshot = await ctx.room_manager.get_snapshot(room_id)
        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=snapshot["current_sequence"],
            now_ms=ctx.now_ms,
            payload={"status": "ok", "room_user_count": snapshot["user_count"]},
        )
        return HandlerResult(ack=ack, broadcasts=broadcasts, close_connection=True)
