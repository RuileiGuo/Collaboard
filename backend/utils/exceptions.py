"""Shared exception types for the backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.core.models import ErrorCode


class CollabBoardError(Exception):
    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class ProtocolValidationError(CollabBoardError):
    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, error_code=ErrorCode.INVALID_MESSAGE, details=details)


class RoomNotFoundError(CollabBoardError):
    def __init__(self, room_id: str) -> None:
        super().__init__(
            f"Room not found: {room_id}",
            error_code=ErrorCode.ROOM_NOT_FOUND,
            details={"room_id": room_id},
        )


class UnauthorizedError(CollabBoardError):
    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, error_code=ErrorCode.UNAUTHORIZED, details=details)


class RateLimitExceededError(CollabBoardError):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, error_code=ErrorCode.RATE_LIMIT)


class UserAlreadyJoinedError(CollabBoardError):
    def __init__(self, user_id: str, room_id: str) -> None:
        super().__init__(
            f"User {user_id} already joined room {room_id}",
            error_code=ErrorCode.USER_ALREADY_JOINED,
            details={"user_id": user_id, "room_id": room_id},
        )


class RoomEventRateLimitError(CollabBoardError):
    """Emitted when a room exceeds configured broadcast/event throughput (protocol §9.2)."""

    def __init__(self, room_id: str) -> None:
        super().__init__(
            "Room event rate limit exceeded",
            error_code=ErrorCode.RATE_LIMIT,
            details={"room_id": room_id, "scope": "room_events"},
        )
