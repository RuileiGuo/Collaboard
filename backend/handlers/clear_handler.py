"""CLEAR message handler."""

from __future__ import annotations

from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import ErrorCode, MessageType


class ClearHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        _payload = dict(message.get("payload", {}))

        if not ctx.state_manager.validate_user_action(user_id, MessageType.CLEAR):
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

        return HandlerResult(
            ack=ctx.error_builder.build_error(
                ErrorCode.CLEAR_REQUIRES_CONSENSUS,
                now_ms=ctx.now_ms,
                request_msg_id=msg_id,
                room_id=room_id,
                details={"use": "clear_propose_then_clear_vote"},
            )
        )
