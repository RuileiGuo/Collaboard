"""FastAPI application entrypoint for the CollabBoard backend."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

FASTAPI_IMPORT_ERROR = None
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    FASTAPI_IMPORT_ERROR = exc
    FastAPI = Any  # type: ignore[assignment]
    WebSocket = Any  # type: ignore[assignment]
    FileResponse = Any  # type: ignore[assignment]
    StaticFiles = Any  # type: ignore[assignment]

    class WebSocketDisconnect(Exception):
        pass

from backend import config
from backend.core.connection_manager import ConnectionManager
from backend.core.message_router import MessageRouter, RouterConfig
from backend.core.room_manager import RoomManager
from backend.core.schemas import validate_client_message
from backend.core.state_manager import StateManager
from backend.handlers.annotation_delete_handler import AnnotationDeleteHandler
from backend.handlers.annotation_delete_request_handler import AnnotationDeleteRequestHandler
from backend.handlers.annotation_delete_vote_handler import AnnotationDeleteVoteHandler
from backend.handlers.annotation_handler import AnnotationHandler
from backend.handlers.annotation_restore_handler import AnnotationRestoreHandler
from backend.handlers.clear_handler import ClearHandler
from backend.handlers.clear_propose_handler import ClearProposeHandler
from backend.handlers.clear_vote_handler import ClearVoteHandler
from backend.handlers.draw_handler import DrawHandler
from backend.handlers.draw_redo_handler import DrawRedoHandler
from backend.handlers.draw_undo_handler import DrawUndoHandler
from backend.core.models import ErrorCode, UserState
from backend.handlers.error_handler import ErrorBuilder
from backend.handlers.join_handler import JoinHandler
from backend.handlers.leave_handler import LeaveHandler
from backend.handlers.proposal_side_effects import emit_room_broadcast_after_append
from backend.handlers.state_sync_handler import StateSyncHandler
from backend.utils.logger import configure_logging, get_logger


logger = get_logger(__name__)


async def _cleanup_disconnected_user(app: FastAPI, user_id: str, room_id: str, reason: str) -> None:
    room_manager: RoomManager = app.state.room_manager
    connection_manager: ConnectionManager = app.state.connection_manager
    state_manager: StateManager = app.state.state_manager
    error_builder: ErrorBuilder = app.state.error_builder

    room = await room_manager.get(room_id)
    if room is None or not await room_manager.is_user_in_room(room_id, user_id):
        return

    current_state = state_manager.get_user_state(user_id)
    if current_state in (UserState.JOINED, UserState.ACTIVE, UserState.IDLE):
        state_manager.on_leave(user_id)

    user_name = await room_manager.get_user_display_name(room_id, user_id)

    proposal_msgs = await room_manager.collect_clear_proposal_messages_on_user_exit(
        room_id, user_id, error_builder, int(time.time() * 1000)
    )
    for msg in proposal_msgs:
        await emit_room_broadcast_after_append(
            room_manager=room_manager,
            connection_manager=connection_manager,
            room_id=room_id,
            message=msg,
        )

    room = await room_manager.leave(room_id, user_id)
    user_left = error_builder.build_broadcast(
        str(uuid.uuid4()),
        room_id,
        user_id,
        payload={
            "event_type": "user_left",
            "user_id": user_id,
            "user_name": user_name,
            "reason": reason,
            "remaining_users": len(room.users),
        },
    )
    user_left["sequence_id"] = await room_manager.append_event(room_id, user_left)
    await connection_manager.broadcast(room_id, user_left, exclude_user_id=user_id)

    if len(room.users) == 0:
        room_idle = error_builder.build_broadcast(
            str(uuid.uuid4()),
            room_id,
            "server",
            payload={"event_type": "room_idle", "room_id": room_id, "ttl_seconds": 60},
        )
        room_idle["sequence_id"] = await room_manager.append_event(room_id, room_idle)
        await connection_manager.broadcast(room_id, room_idle)


async def _ensure_user_session_for_connection(
    state_manager: StateManager,
    connection_manager: ConnectionManager,
    connection_id: str,
) -> None:
    """Restore ACTIVE session when WebSocket is still open but idle timeouts marked user DISCONNECTED."""
    connection = await connection_manager.get_connection(connection_id)
    if not connection or not connection.user_id or not connection.room_id:
        return
    user_id = connection.user_id
    room_id = connection.room_id
    try:
        current = state_manager.get_user_state(user_id)
    except Exception:
        return
    if current in (UserState.DISCONNECTED, UserState.TIMEOUT):
        state_manager.restore_room_session(
            user_id,
            room_id,
            connection_id=connection_id,
        )


async def _maintenance_loop(app: FastAPI) -> None:
    state_manager: StateManager = app.state.state_manager
    room_manager: RoomManager = app.state.room_manager
    connection_manager: ConnectionManager = app.state.connection_manager

    while True:
        online_users = await connection_manager.list_connected_user_ids()
        for event in state_manager.apply_timeouts(online_user_ids=online_users):
            if event.to_state == "disconnected":
                entry = await connection_manager.get_connection_by_user(event.entity_id)
                if entry is not None:
                    await connection_manager.disconnect(entry.connection_id, reason=event.reason)
        await room_manager.expire_rooms()
        now_ms = int(time.time() * 1000)
        for rid, msg in await room_manager.sweep_expired_clear_proposals(now_ms, app.state.error_builder):
            await emit_room_broadcast_after_append(
                room_manager=room_manager,
                connection_manager=connection_manager,
                room_id=rid,
                message=msg,
            )
        await asyncio.sleep(config.MAINTENANCE_INTERVAL_SECONDS)


def create_app() -> FastAPI:
    if FASTAPI_IMPORT_ERROR is not None:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "fastapi is required to run the websocket application. "
            "Install backend/requirements.txt first."
        ) from FASTAPI_IMPORT_ERROR

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        app.state.error_builder = ErrorBuilder()
        app.state.connection_manager = ConnectionManager(
            send_timeout_s=config.WEBSOCKET_SEND_TIMEOUT_SECONDS,
            close_timeout_s=config.WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
        )
        app.state.room_manager = RoomManager()
        app.state.state_manager = StateManager()
        app.state.router = MessageRouter(
            handlers={
                "join": JoinHandler(),
                "leave": LeaveHandler(),
                "draw": DrawHandler(),
                "draw_undo": DrawUndoHandler(),
                "draw_redo": DrawRedoHandler(),
                "annotation": AnnotationHandler(),
                "annotation_delete": AnnotationDeleteHandler(),
                "annotation_delete_request": AnnotationDeleteRequestHandler(),
                "annotation_delete_vote": AnnotationDeleteVoteHandler(),
                "annotation_restore": AnnotationRestoreHandler(),
                "clear": ClearHandler(),
                "clear_propose": ClearProposeHandler(),
                "clear_vote": ClearVoteHandler(),
                "state_sync": StateSyncHandler(),
            },
            connection_manager=app.state.connection_manager,
            room_manager=app.state.room_manager,
            state_manager=app.state.state_manager,
            schema_validator=validate_client_message,
            error_builder=app.state.error_builder,
            config=RouterConfig(
                max_message_bytes=config.MESSAGE_MAX_BYTES,
                timestamp_tolerance_sec=config.TIMESTAMP_TOLERANCE_SECONDS,
                dedup_ttl_sec=config.DEDUP_WINDOW_SECONDS,
                rate_capacity=config.RATE_LIMIT_MESSAGES_PER_SECOND,
                rate_refill_per_sec=float(config.RATE_LIMIT_MESSAGES_PER_SECOND),
            ),
        )
        maintenance_task = asyncio.create_task(_maintenance_loop(app))
        try:
            yield
        finally:
            maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance_task

    app = FastAPI(title=config.APP_NAME, lifespan=lifespan)
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    if frontend_dir.exists():
        app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> Any:
        index_file = frontend_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"status": "frontend_not_found"}

    @app.websocket("/ws/{connection_id}")
    async def websocket_endpoint(websocket: WebSocket, connection_id: str) -> None:
        connection_manager: ConnectionManager = app.state.connection_manager
        state_manager: StateManager = app.state.state_manager
        router: MessageRouter = app.state.router
        error_builder: ErrorBuilder = app.state.error_builder

        await websocket.accept()
        if await connection_manager.is_connection_id_taken(connection_id):
            duplicate_ack = error_builder.build_error(
                ErrorCode.CONNECTION_ALREADY_EXISTS,
                details={"connection_id": connection_id},
            )
            await websocket.send_text(json.dumps(duplicate_ack, separators=(",", ":"), ensure_ascii=True))
            await websocket.close(code=4001, reason="connection_id already in use")
            return

        await connection_manager.register(connection_id, websocket)

        try:
            while True:
                raw_text = await websocket.receive_text()
                try:
                    preview = json.loads(raw_text)
                except json.JSONDecodeError:
                    preview = None
                reject_user_bind = False
                if isinstance(preview, dict):
                    user_id = preview.get("user_id")
                    if isinstance(user_id, str):
                        connection = await connection_manager.get_connection(connection_id)
                        if connection and connection.user_id is None:
                            preview_room = preview.get("room_id")
                            duplicate = False
                            duplicate_details: dict[str, object] = {"user_id": user_id}
                            if isinstance(preview_room, str) and preview_room:
                                in_room = await connection_manager.find_user_connection_in_room(
                                    preview_room,
                                    user_id,
                                    exclude_connection_id=connection_id,
                                )
                                if in_room is not None:
                                    duplicate = True
                                    duplicate_details = {
                                        "user_id": user_id,
                                        "room_id": preview_room,
                                        "reason": "duplicate_user_id_in_room",
                                        "occupant_connection_id": in_room.connection_id,
                                    }
                            existing = await connection_manager.get_connection_by_user(user_id)
                            if existing and existing.connection_id != connection_id:
                                duplicate = True
                                if "reason" not in duplicate_details:
                                    duplicate_details["reason"] = "user_id_globally_bound"
                            if duplicate:
                                duplicate_user_ack = error_builder.build_error(
                                    ErrorCode.USER_ALREADY_JOINED,
                                    message="User ID already in use in this room"
                                    if duplicate_details.get("reason") == "duplicate_user_id_in_room"
                                    else "User ID already in use",
                                    request_msg_id=str(preview.get("msg_id"))
                                    if preview.get("msg_id")
                                    else None,
                                    details=duplicate_details,
                                )
                                await connection_manager.send(connection_id, duplicate_user_ack)
                                reject_user_bind = True
                            else:
                                state_manager.on_connected(user_id, connection_id=connection_id)
                                await connection_manager.register(connection_id, user_id=user_id)

                if reject_user_bind:
                    break

                online_users = await connection_manager.list_connected_user_ids()
                state_manager.apply_timeouts(online_user_ids=online_users)
                await _ensure_user_session_for_connection(
                    state_manager,
                    connection_manager,
                    connection_id,
                )

                result = await router.handle_raw(raw_text, connection_id=connection_id)
                await connection_manager.send(connection_id, result.ack)
                for instruction in result.broadcasts:
                    await connection_manager.broadcast(
                        instruction.room_id,
                        instruction.message,
                        exclude_user_id=instruction.exclude_user_id,
                    )
                if result.close_connection:
                    break
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: %s", connection_id)
        finally:
            connection = await connection_manager.get_connection(connection_id)
            if connection and connection.user_id:
                if connection.room_id:
                    await _cleanup_disconnected_user(app, connection.user_id, connection.room_id, "disconnect")
                state_manager.on_disconnect(connection.user_id)
            await connection_manager.disconnect(connection_id, reason="connection_closed")

    return app

app = create_app() if FASTAPI_IMPORT_ERROR is None else None
