"""CLEAR_PROPOSE — start unanimous clear vote (or immediate clear if sole occupant)."""

from __future__ import annotations

import uuid
from typing import Mapping

from backend import config
from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import (
    BroadcastEventType,
    BroadcastInstruction,
    ClearProposalState,
    ErrorCode,
    MessageType,
)
from backend.handlers.proposal_side_effects import maybe_emit_expired_clear_proposal_for_room


class ClearProposeHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))

        await maybe_emit_expired_clear_proposal_for_room(
            room_manager=ctx.room_manager,
            connection_manager=ctx.connection_manager,
            room_id=room_id,
            now_ms=ctx.now_ms,
            error_builder=ctx.error_builder,
        )

        if not ctx.state_manager.validate_user_action(user_id, MessageType.CLEAR_PROPOSE):
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

        proposal_id = str(uuid.uuid4())
        expires_ms = ctx.now_ms + int(config.CLEAR_PROPOSAL_TTL_MS)
        note = str(payload.get("message", ""))[:500]

        immediate_clear = False
        required: set[str] = set()

        async with room.lock:
            if room.clear_proposal is not None:
                return HandlerResult(
                    ack=ctx.error_builder.build_error(
                        ErrorCode.CLEAR_PROPOSAL_ACTIVE,
                        now_ms=ctx.now_ms,
                        request_msg_id=msg_id,
                        room_id=room_id,
                    )
                )
            required = set(room.users)
            approvals = {user_id}
            if required <= approvals:
                immediate_clear = True
            else:
                room.clear_proposal = ClearProposalState(
                    proposal_id=proposal_id,
                    proposer_id=user_id,
                    required_voters=set(required),
                    approvals=set(approvals),
                    expires_ms=expires_ms,
                )

        ctx.state_manager.on_activity(user_id, message_type=MessageType.CLEAR_PROPOSE)

        proposer_name = await ctx.room_manager.get_user_display_name(room_id, user_id)

        if immediate_clear:
            broadcast = ctx.error_builder.build_broadcast(
                msg_id,
                room_id,
                user_id,
                payload={
                    "event_type": BroadcastEventType.CLEAR.value,
                    "user_id": user_id,
                    "user_name": proposer_name,
                    "clear_type": "full",
                    "consensus": True,
                    "proposal_id": proposal_id,
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
                    "cleared": True,
                    "proposal_id": proposal_id,
                    "reason": "single_member_room",
                },
            )
            return HandlerResult(
                ack=ack,
                broadcasts=[BroadcastInstruction(room_id=room_id, message=broadcast)],
            )

        propose_broadcast = ctx.error_builder.build_broadcast(
            msg_id,
            room_id,
            user_id,
            payload={
                "event_type": BroadcastEventType.CLEAR_PROPOSE.value,
                "proposal_id": proposal_id,
                "proposer_id": user_id,
                "proposer_name": proposer_name,
                "required_voters": sorted(required),
                "expires_ms": expires_ms,
                "message": note,
            },
            now_ms=ctx.now_ms,
        )
        sequence_id = await ctx.room_manager.append_event(room_id, propose_broadcast)
        propose_broadcast["sequence_id"] = sequence_id

        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=sequence_id,
            now_ms=ctx.now_ms,
            payload={
                "status": "ok",
                "proposal_id": proposal_id,
                "expires_ms": expires_ms,
                "required_voters": sorted(required),
            },
        )
        return HandlerResult(
            ack=ack,
            broadcasts=[BroadcastInstruction(room_id=room_id, message=propose_broadcast)],
        )
