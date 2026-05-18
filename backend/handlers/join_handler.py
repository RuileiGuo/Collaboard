"""JOIN message handler."""

from __future__ import annotations

from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType, UserState
from backend.utils.exceptions import UserAlreadyJoinedError


class JoinHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))
        metadata = dict(payload.get("metadata", {}))
        user_name = str(metadata.get("user_name", user_id))

        current_state = ctx.state_manager.get_user_state(user_id)
        if not ctx.state_manager.validate_user_action(user_id, MessageType.JOIN):
            error_code = ErrorCode.USER_ALREADY_JOINED if current_state != UserState.CONNECTED else ErrorCode.UNAUTHORIZED
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    error_code,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"user_id": user_id, "state": current_state.value},
                )
            )

        existing_room = await ctx.room_manager.find_room_for_user(user_id)
        if existing_room is not None and existing_room != room_id:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.USER_ALREADY_JOINED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    message="User is already in another room",
                    details={"user_id": user_id, "room_id": existing_room},
                )
            )

        try:
            await ctx.room_manager.join(room_id, user_id, metadata=metadata)
        except UserAlreadyJoinedError as exc:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.USER_ALREADY_JOINED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    message=str(exc),
                    details={"user_id": user_id, "room_id": room_id},
                )
            )
        ctx.state_manager.on_join(user_id, room_id)
        await ctx.connection_manager.register(ctx.connection_id, user_id=user_id, room_id=room_id)

        broadcast = ctx.error_builder.build_broadcast(
            msg_id,
            room_id,
            user_id,
            payload={
                "event_type": BroadcastEventType.USER_JOINED.value,
                "user_id": user_id,
                "user_name": user_name,
            },
            now_ms=ctx.now_ms,
        )
        sequence_id = await ctx.room_manager.append_event(room_id, broadcast)
        broadcast["sequence_id"] = sequence_id

        snapshot = await ctx.room_manager.get_snapshot(room_id)
        broadcast["payload"]["room_user_count"] = snapshot["user_count"]

        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=snapshot["current_sequence"],
            now_ms=ctx.now_ms,
            payload={"status": "ok", "reason": "joined", "room_state": snapshot},
        )
        return HandlerResult(
            ack=ack,
            broadcasts=[
                BroadcastInstruction(
                    room_id=room_id,
                    message=broadcast,
                    exclude_user_id=user_id,
                )
            ],
        )
