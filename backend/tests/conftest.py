from __future__ import annotations

import json
import time
import uuid

from backend.core.connection_manager import ConnectionManager
from backend.core.message_router import MessageRouter, RouterConfig
from backend.core.room_manager import RoomManager
from backend.core.schemas import validate_client_message
from backend.core.state_manager import StateManager
from backend.handlers.annotation_delete_handler import AnnotationDeleteHandler
from backend.handlers.annotation_handler import AnnotationHandler
from backend.handlers.annotation_restore_handler import AnnotationRestoreHandler
from backend.handlers.clear_handler import ClearHandler
from backend.handlers.clear_propose_handler import ClearProposeHandler
from backend.handlers.clear_vote_handler import ClearVoteHandler
from backend.handlers.draw_handler import DrawHandler
from backend.handlers.draw_redo_handler import DrawRedoHandler
from backend.handlers.draw_undo_handler import DrawUndoHandler
from backend.handlers.error_handler import ErrorBuilder
from backend.handlers.join_handler import JoinHandler
from backend.handlers.leave_handler import LeaveHandler
from backend.handlers.state_sync_handler import StateSyncHandler


class FakeWebSocket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.fail_send = fail_send
        self.sent = []
        self.closed = False

    async def send_json(self, message):
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(message)

    async def send_text(self, message):
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(json.loads(message))

    async def close(self, code: int = 1000, reason: str | None = None):
        self.closed = True


def build_message(message_type: str, user_id: str, room_id: str, payload: dict, *, msg_id: str | None = None) -> dict:
    return {
        "msg_id": msg_id or str(uuid.uuid4()),
        "type": message_type,
        "timestamp": int(time.time() * 1000),
        "user_id": user_id,
        "room_id": room_id,
        "sequence_id": None,
        "payload": payload,
    }


def create_backend_stack():
    connection_manager = ConnectionManager()
    room_manager = RoomManager()
    state_manager = StateManager()
    error_builder = ErrorBuilder()
    router = MessageRouter(
        handlers={
            "join": JoinHandler(),
            "leave": LeaveHandler(),
            "draw": DrawHandler(),
            "draw_undo": DrawUndoHandler(),
            "draw_redo": DrawRedoHandler(),
            "annotation": AnnotationHandler(),
            "annotation_delete": AnnotationDeleteHandler(),
            "annotation_restore": AnnotationRestoreHandler(),
            "clear": ClearHandler(),
            "clear_propose": ClearProposeHandler(),
            "clear_vote": ClearVoteHandler(),
            "state_sync": StateSyncHandler(),
        },
        connection_manager=connection_manager,
        room_manager=room_manager,
        state_manager=state_manager,
        schema_validator=validate_client_message,
        error_builder=error_builder,
        config=RouterConfig(),
    )
    return {
        "connection_manager": connection_manager,
        "room_manager": room_manager,
        "state_manager": state_manager,
        "error_builder": error_builder,
        "router": router,
    }
