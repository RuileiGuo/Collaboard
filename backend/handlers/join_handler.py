"""JOIN message handler."""

from __future__ import annotations

from contextlib import suppress
from typing import Mapping

from backend.core.message_router import HandlerContext, HandlerResult
from backend.core.models import BroadcastEventType, BroadcastInstruction, ErrorCode, MessageType, UserState
from backend.utils.exceptions import UserAlreadyJoinedError


class JoinHandler:
    @staticmethod
    def _duplicate_in_room_error(
        ctx: HandlerContext,
        *,
        msg_id: str,
        room_id: str,
        user_id: str,
        reason: str,
        message: str,
        occupant_connection_id: str | None = None,
        occupant_user_id: str | None = None,
        user_name: str | None = None,
    ) -> HandlerResult:
        details: dict[str, object] = {
            "user_id": user_id,
            "room_id": room_id,
            "reason": reason,
        }
        if occupant_connection_id:
            details["occupant_connection_id"] = occupant_connection_id
        if occupant_user_id:
            details["occupant_user_id"] = occupant_user_id
        if user_name is not None:
            details["user_name"] = user_name
        return HandlerResult(
            ack=ctx.error_builder.build_error(
                ErrorCode.USER_ALREADY_JOINED,
                now_ms=ctx.now_ms,
                request_msg_id=msg_id,
                room_id=room_id,
                message=message,
                details=details,
            )
        )

    async def _ensure_display_name_available(
        self,
        ctx: HandlerContext,
        *,
        room_id: str,
        user_id: str,
        user_name: str,
        msg_id: str,
    ) -> HandlerResult | None:
        owner_id = await ctx.room_manager.find_user_id_by_display_name(
            room_id,
            user_name,
            exclude_user_id=user_id,
        )
        if owner_id is None:
            return None
        live = await ctx.connection_manager.find_user_connection_in_room(room_id, owner_id)
        if live is not None:
            return self._duplicate_in_room_error(
                ctx,
                msg_id=msg_id,
                room_id=room_id,
                user_id=user_id,
                reason="duplicate_user_name_in_room",
                message="User name already in use in this room",
                occupant_connection_id=live.connection_id,
                occupant_user_id=owner_id,
                user_name=user_name,
            )
        if await ctx.room_manager.is_user_in_room(room_id, owner_id):
            with suppress(Exception):
                ctx.state_manager.on_leave(owner_id, now=ctx.now_ms / 1000.0)
            await ctx.room_manager.leave(room_id, owner_id)
        return None

    async def _build_join_success(
        self,
        ctx: HandlerContext,
        *,
        msg_id: str,
        room_id: str,
        user_id: str,
        user_name: str,
        emit_user_joined: bool,
    ) -> HandlerResult:
        broadcast: dict[str, object] | None = None
        if emit_user_joined:
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
        if broadcast is not None:
            broadcast["payload"]["room_user_count"] = snapshot["user_count"]

        ack = ctx.error_builder.build_ack(
            msg_id,
            room_id,
            sequence_id=snapshot["current_sequence"],
            now_ms=ctx.now_ms,
            payload={"status": "ok", "reason": "joined", "room_state": snapshot},
        )
        broadcasts = []
        if broadcast is not None:
            broadcasts.append(
                BroadcastInstruction(
                    room_id=room_id,
                    message=broadcast,
                    exclude_user_id=user_id,
                )
            )
        return HandlerResult(ack=ack, broadcasts=broadcasts)

    async def handle(self, ctx: HandlerContext, message: Mapping[str, object]) -> HandlerResult:
        user_id = str(message["user_id"])
        room_id = str(message["room_id"])
        msg_id = str(message["msg_id"])
        payload = dict(message.get("payload", {}))
        metadata = dict(payload.get("metadata", {}))
        user_name = str(metadata.get("user_name", user_id))

        occupant = await ctx.connection_manager.find_user_connection_in_room(
            room_id,
            user_id,
            exclude_connection_id=ctx.connection_id,
        )
        if occupant is not None:
            return self._duplicate_in_room_error(
                ctx,
                msg_id=msg_id,
                room_id=room_id,
                user_id=user_id,
                reason="duplicate_user_id_in_room",
                message="User ID already in use in this room",
                occupant_connection_id=occupant.connection_id,
            )

        name_conflict = await self._ensure_display_name_available(
            ctx,
            room_id=room_id,
            user_id=user_id,
            user_name=user_name,
            msg_id=msg_id,
        )
        if name_conflict is not None:
            return name_conflict

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

        if await ctx.room_manager.is_user_in_room(room_id, user_id):
            live = await ctx.connection_manager.find_user_connection_in_room(
                room_id,
                user_id,
                exclude_connection_id=ctx.connection_id,
            )
            if live is not None:
                return self._duplicate_in_room_error(
                    ctx,
                    msg_id=msg_id,
                    room_id=room_id,
                    user_id=user_id,
                    reason="duplicate_user_id_in_room",
                    message="User ID already in use in this room",
                    occupant_connection_id=live.connection_id,
                )
            self_conn = await ctx.connection_manager.get_connection(ctx.connection_id)
            if (
                self_conn is not None
                and self_conn.user_id == user_id
                and self_conn.room_id == room_id
            ):
                ctx.state_manager.restore_room_session(
                    user_id,
                    room_id,
                    connection_id=ctx.connection_id,
                    now=ctx.now_ms / 1000.0,
                )
                await ctx.connection_manager.register(
                    ctx.connection_id,
                    user_id=user_id,
                    room_id=room_id,
                )
                return await self._build_join_success(
                    ctx,
                    msg_id=msg_id,
                    room_id=room_id,
                    user_id=user_id,
                    user_name=user_name,
                    emit_user_joined=False,
                )
            with suppress(Exception):
                ctx.state_manager.on_leave(user_id, now=ctx.now_ms / 1000.0)
            await ctx.room_manager.leave(room_id, user_id)

        try:
            await ctx.room_manager.join(room_id, user_id, metadata=metadata)
        except UserAlreadyJoinedError:
            occupant = await ctx.connection_manager.find_user_connection_in_room(
                room_id,
                user_id,
                exclude_connection_id=ctx.connection_id,
            )
            if occupant is not None:
                return self._duplicate_in_room_error(
                    ctx,
                    msg_id=msg_id,
                    room_id=room_id,
                    user_id=user_id,
                    reason="duplicate_user_id_in_room",
                    message="User ID already in use in this room",
                    occupant_connection_id=occupant.connection_id,
                )
            name_conflict = await self._ensure_display_name_available(
                ctx,
                room_id=room_id,
                user_id=user_id,
                user_name=user_name,
                msg_id=msg_id,
            )
            if name_conflict is not None:
                return name_conflict
            return HandlerResult(
                ack=ctx.error_builder.build_error(
                    ErrorCode.USER_ALREADY_JOINED,
                    now_ms=ctx.now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id,
                    message="User ID already in use in this room",
                    details={
                        "user_id": user_id,
                        "room_id": room_id,
                        "reason": "duplicate_user_id_in_room",
                    },
                )
            )
        ctx.state_manager.on_join(user_id, room_id)
        await ctx.connection_manager.register(ctx.connection_id, user_id=user_id, room_id=room_id)
        return await self._build_join_success(
            ctx,
            msg_id=msg_id,
            room_id=room_id,
            user_id=user_id,
            user_name=user_name,
            emit_user_joined=True,
        )
