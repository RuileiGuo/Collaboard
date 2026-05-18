"""ANNOTATION_DELETE_VOTE - author approves or rejects a pending annotation delete request."""

from __future__ import annotations

import uuid
from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType


class AnnotationDeleteVoteHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))
        request_id = str(payload["request_id"])
        annotation_id = str(payload["annotation_id"])
        vote = str(payload["vote"])

        if not ctx.state_manager.validate_user_action(user_id, MessageType.ANNOTATION_DELETE_VOTE):
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

        req = await ctx.room_manager.get_annotation_delete_request(room_id, annotation_id)
        if req is None or req.request_id != request_id:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ANNOTATION_DELETE_REQUEST_NOT_FOUND,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"annotation_id": annotation_id, "request_id": request_id},
                )
            )

        if ctx.now_ms >= req.expires_ms:
            await ctx.room_manager.pop_annotation_delete_request(room_id, annotation_id)
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ANNOTATION_DELETE_REQUEST_NOT_FOUND,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    message="Annotation delete request expired",
                    details={"annotation_id": annotation_id, "request_id": request_id},
                )
            )

        if req.target_author_id != user_id:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.UNAUTHORIZED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    message="Only the annotation author may vote on this delete request",
                    details={"annotation_id": annotation_id, "request_id": request_id},
                )
            )

        visible, author = await ctx.room_manager.annotation_visible_and_author(room_id, annotation_id)
        if not visible or author != user_id:
            await ctx.room_manager.pop_annotation_delete_request(room_id, annotation_id)
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ANNOTATION_NOT_FOUND,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"annotation_id": annotation_id},
                )
            )

        ctx.state_manager.on_activity(user_id, message_type=MessageType.ANNOTATION_DELETE_VOTE)
        await ctx.room_manager.pop_annotation_delete_request(room_id, annotation_id)

        if vote == "reject":
            rejector_name = await ctx.room_manager.get_user_display_name(room_id, user_id)
            reject_broadcast = ctx.error_builder.build_broadcast(
                str(uuid.uuid4()),
                room_id,
                user_id,
                payload={
                    "event_type": BroadcastEventType.ANNOTATION_DELETE_REJECTED.value,
                    "request_id": request_id,
                    "annotation_id": annotation_id,
                    "rejector_id": user_id,
                    "rejector_name": rejector_name,
                    "requester_id": req.requester_id,
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
                payload={
                    "status": "ok",
                    "op": "annotation_delete_vote",
                    "vote": "reject",
                    "annotation_id": annotation_id,
                    "request_id": request_id,
                },
            )
            return HandlerResult(
                ack=ack,
                broadcasts=[BroadcastInstruction(room_id=room_id, message=reject_broadcast)],
            )

        remover_name = await ctx.room_manager.get_user_display_name(room_id, user_id)
        removed_broadcast = ctx.error_builder.build_broadcast(
            str(uuid.uuid4()),
            room_id,
            user_id,
            payload={
                "event_type": BroadcastEventType.ANNOTATION_REMOVED.value,
                "annotation_id": annotation_id,
                "user_id": user_id,
                "user_name": remover_name,
                "approved_request_id": request_id,
                "requested_by": req.requester_id,
            },
            now_ms=ctx.now_ms,
        )
        seq_d = await ctx.room_manager.append_event(room_id, removed_broadcast)
        removed_broadcast["sequence_id"] = seq_d
        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=seq_d,
            now_ms=ctx.now_ms,
            payload={
                "status": "ok",
                "op": "annotation_delete_vote",
                "vote": "approve",
                "annotation_id": annotation_id,
                "request_id": request_id,
                "server_sequence": seq_d,
            },
        )
        return HandlerResult(
            ack=ack,
            broadcasts=[BroadcastInstruction(room_id=room_id, message=removed_broadcast)],
        )
