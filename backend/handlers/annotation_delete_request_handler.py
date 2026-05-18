"""ANNOTATION_DELETE_REQUEST - request deletion of another user's annotation."""

from __future__ import annotations

import uuid
from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType


ANNOTATION_DELETE_REQUEST_TTL_MS = 120_000


class AnnotationDeleteRequestHandler:
    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))
        annotation_id = str(payload["annotation_id"])
        note = str(payload.get("message", ""))[:300]

        if not ctx.state_manager.validate_user_action(user_id, MessageType.ANNOTATION_DELETE_REQUEST):
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

        visible, author = await ctx.room_manager.annotation_visible_and_author(room_id, annotation_id)
        if not visible or not author:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ANNOTATION_NOT_FOUND,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"annotation_id": annotation_id},
                )
            )

        if author == user_id:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.INVALID_MESSAGE,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    message="Use annotation_delete for your own annotation",
                    details={"annotation_id": annotation_id},
                )
            )

        existing = await ctx.room_manager.get_annotation_delete_request(room_id, annotation_id)
        if existing is not None and ctx.now_ms < existing.expires_ms:
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.ANNOTATION_DELETE_REQUEST_ACTIVE,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    details={"annotation_id": annotation_id, "request_id": existing.request_id},
                )
            )

        if existing is not None:
            await ctx.room_manager.pop_annotation_delete_request(room_id, annotation_id)

        request_id = str(uuid.uuid4())
        expires_ms = ctx.now_ms + ANNOTATION_DELETE_REQUEST_TTL_MS
        await ctx.room_manager.create_annotation_delete_request(
            room_id,
            annotation_id=annotation_id,
            requester_id=user_id,
            target_author_id=author,
            request_id=request_id,
            expires_ms=expires_ms,
        )

        ctx.state_manager.on_activity(user_id, message_type=MessageType.ANNOTATION_DELETE_REQUEST)
        requester_name = await ctx.room_manager.get_user_display_name(room_id, user_id)
        author_name = await ctx.room_manager.get_user_display_name(room_id, author)
        broadcast = ctx.error_builder.build_broadcast(
            msg_id,
            room_id,
            user_id,
            payload={
                "event_type": BroadcastEventType.ANNOTATION_DELETE_REQUESTED.value,
                "request_id": request_id,
                "annotation_id": annotation_id,
                "requester_id": user_id,
                "requester_name": requester_name,
                "target_author_id": author,
                "target_author_name": author_name,
                "message": note,
                "expires_ms": expires_ms,
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
                "op": "annotation_delete_request",
                "annotation_id": annotation_id,
                "request_id": request_id,
                "expires_ms": expires_ms,
            },
        )
        return HandlerResult(
            ack=ack,
            broadcasts=[BroadcastInstruction(room_id=room_id, message=broadcast)],
        )
