"""CLEAR_VOTE — approve or reject a pending clear proposal."""

from __future__ import annotations

import uuid
from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType
from backend.handlers.proposal_side_effects import maybe_emit_expired_clear_proposal_for_room


class ClearVoteHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))
        proposal_id = str(payload["proposal_id"])
        vote = str(payload["vote"])

        await maybe_emit_expired_clear_proposal_for_room(
            room_manager=ctx.room_manager,
            connection_manager=ctx.connection_manager,
            room_id=room_id,
            now_ms=ctx.now_ms,
            error_builder=ctx.error_builder,
        )

        if not ctx.state_manager.validate_user_action(user_id, MessageType.CLEAR_VOTE):
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

        ctx.state_manager.on_activity(user_id, message_type=MessageType.CLEAR_VOTE)

        action = "error"
        proposer_id_out = ""
        async with room.lock:
            cp = room.clear_proposal
            if cp is None or cp.proposal_id != proposal_id:
                return HandlerResult(
                    ack=ctx.error_builder.build_error(
                        ErrorCode.CLEAR_PROPOSAL_NOT_FOUND,
                        now_ms=ctx.now_ms,
                        request_msg_id=msg_id,
                        room_id=room_id,
                        details={"proposal_id": proposal_id},
                    )
                )
            if ctx.now_ms >= cp.expires_ms:
                room.clear_proposal = None
                return HandlerResult(
                    ack=ctx.error_builder.build_error(
                        ErrorCode.CLEAR_PROPOSAL_NOT_FOUND,
                        now_ms=ctx.now_ms,
                        request_msg_id=msg_id,
                        room_id=room_id,
                        message="Clear proposal expired",
                        details={"proposal_id": proposal_id},
                    )
                )
            if user_id not in cp.required_voters:
                return HandlerResult(
                    ack=ctx.error_builder.build_error(
                        ErrorCode.UNAUTHORIZED,
                        now_ms=ctx.now_ms,
                        request_msg_id=msg_id,
                        room_id=room_id,
                        message="Not a required voter for this proposal",
                    )
                )
            if user_id in cp.approvals and vote == "approve":
                return HandlerResult(
                    ack=ctx.error_builder.build_error(
                        ErrorCode.CLEAR_VOTE_DUPLICATE,
                        now_ms=ctx.now_ms,
                        request_msg_id=msg_id,
                        room_id=room_id,
                    )
                )

            if vote == "reject":
                room.clear_proposal = None
                action = "reject"
            else:
                cp.approvals.add(user_id)
                proposer_id_out = cp.proposer_id
                if cp.required_voters <= cp.approvals:
                    room.clear_proposal = None
                    action = "consensus"
                else:
                    action = "approve_pending"

        if action == "reject":
            reject_name = await ctx.room_manager.get_user_display_name(room_id, user_id)
            reject_broadcast = ctx.error_builder.build_broadcast(
                str(uuid.uuid4()),
                room_id,
                user_id,
                payload={
                    "event_type": BroadcastEventType.CLEAR_REJECTED.value,
                    "proposal_id": proposal_id,
                    "rejector_id": user_id,
                    "rejector_name": reject_name,
                },
                now_ms=ctx.now_ms,
            )
            seq_r = await ctx.room_manager.append_event(room_id, reject_broadcast)
            reject_broadcast["sequence_id"] = seq_r
            ack = ctx.error_builder.build_ack(
                msg_id,
                room_id,
                sequence_id=seq_r,
                now_ms=ctx.now_ms,
                payload={"status": "ok", "vote": "reject", "proposal_id": proposal_id},
            )
            return HandlerResult(
                ack=ack,
                broadcasts=[BroadcastInstruction(room_id=room_id, message=reject_broadcast)],
            )

        if action == "approve_pending":
            snapshot = await ctx.room_manager.get_snapshot(room_id)
            ack = ctx.error_builder.build_ack(
                msg_id,
                room_id,
                sequence_id=snapshot["current_sequence"],
                now_ms=ctx.now_ms,
                payload={
                    "status": "ok",
                    "vote": "approve",
                    "proposal_id": proposal_id,
                    "pending": True,
                },
            )
            return HandlerResult(ack=ack)

        proposer_name = await ctx.room_manager.get_user_display_name(room_id, proposer_id_out)
        clear_broadcast = ctx.error_builder.build_broadcast(
            str(uuid.uuid4()),
            room_id,
            proposer_id_out,
            payload={
                "event_type": BroadcastEventType.CLEAR.value,
                "user_id": proposer_id_out,
                "user_name": proposer_name,
                "clear_type": "full",
                "consensus": True,
                "proposal_id": proposal_id,
            },
            now_ms=ctx.now_ms,
        )
        seq_c = await ctx.room_manager.append_event(room_id, clear_broadcast)
        clear_broadcast["sequence_id"] = seq_c
        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=seq_c,
            now_ms=ctx.now_ms,
            payload={
                "status": "ok",
                "vote": "approve",
                "proposal_id": proposal_id,
                "cleared": True,
            },
        )
        return HandlerResult(
            ack=ack,
            broadcasts=[BroadcastInstruction(room_id=room_id, message=clear_broadcast)],
        )
