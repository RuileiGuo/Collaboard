"""Message builders for ACK, ERROR, and BROADCAST responses."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from backend.core.models import ErrorCode, MessageType


DEFAULT_ERROR_MESSAGES = {
    ErrorCode.INVALID_MESSAGE: "Invalid message",
    ErrorCode.ROOM_NOT_FOUND: "Room not found",
    ErrorCode.UNAUTHORIZED: "Unauthorized",
    ErrorCode.RATE_LIMIT: "Rate limit exceeded",
    ErrorCode.USER_ALREADY_JOINED: "User already joined",
    ErrorCode.SEQUENCE_CONFLICT: "Sequence conflict",
    ErrorCode.INTERNAL_ERROR: "Internal server error",
    ErrorCode.CLEAR_REQUIRES_CONSENSUS: "Full clear requires clear_propose and unanimous approval",
    ErrorCode.CLEAR_PROPOSAL_ACTIVE: "A clear proposal is already pending",
    ErrorCode.CLEAR_PROPOSAL_NOT_FOUND: "No matching clear proposal",
    ErrorCode.CLEAR_VOTE_DUPLICATE: "Vote already recorded for this proposal",
    ErrorCode.ANNOTATION_NOT_FOUND: "Annotation not found or already removed",
    ErrorCode.STROKE_NOT_FOUND: "Stroke not found or already undone",
}


class ErrorBuilder:
    def build_ack(
        self,
        request_msg_id: str,
        room_id: str,
        *,
        sequence_id: Optional[int],
        payload: Dict[str, Any],
        now_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {
            "msg_id": request_msg_id,
            "type": MessageType.ACK.value,
            "timestamp": self._timestamp(now_ms),
            "user_id": "server",
            "room_id": room_id,
            "sequence_id": sequence_id,
            "payload": payload,
        }

    def build_error(
        self,
        code: ErrorCode,
        *,
        message: Optional[str] = None,
        now_ms: Optional[int] = None,
        request_msg_id: Optional[str] = None,
        room_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "msg_id": request_msg_id,
            "type": MessageType.ERROR.value,
            "timestamp": self._timestamp(now_ms),
            "user_id": "server",
            "room_id": room_id,
            "sequence_id": None,
            "payload": {
                "status": "fail",
                "error_code": code.value,
                "message": message or DEFAULT_ERROR_MESSAGES[code],
                "details": details or {},
            },
        }

    def build_broadcast(
        self,
        request_msg_id: str,
        room_id: str,
        user_id: str,
        *,
        payload: Dict[str, Any],
        sequence_id: Optional[int] = None,
        now_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {
            "msg_id": request_msg_id,
            "type": MessageType.BROADCAST.value,
            "timestamp": self._timestamp(now_ms),
            "user_id": user_id,
            "room_id": room_id,
            "sequence_id": sequence_id,
            "payload": payload,
        }

    @staticmethod
    def _timestamp(now_ms: Optional[int]) -> int:
        return int(time.time() * 1000) if now_ms is None else int(now_ms)
