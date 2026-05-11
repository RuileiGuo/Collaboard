"""Core data models and enums for the CollabBoard backend."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


JsonDict = Dict[str, Any]


class UserState(str, Enum):
    INIT = "init"
    CONNECTED = "connected"
    JOINED = "joined"
    ACTIVE = "active"
    LEFT = "left"
    IDLE = "idle"
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"


class RoomState(str, Enum):
    PENDING_INIT = "pending_init"
    ACTIVE = "active"
    IDLE = "idle"
    DESTROYED = "destroyed"


class MessageType(str, Enum):
    JOIN = "join"
    LEAVE = "leave"
    DRAW = "draw"
    ANNOTATION = "annotation"
    ANNOTATION_DELETE = "annotation_delete"
    ANNOTATION_RESTORE = "annotation_restore"
    DRAW_UNDO = "draw_undo"
    DRAW_REDO = "draw_redo"
    CLEAR = "clear"
    CLEAR_PROPOSE = "clear_propose"
    CLEAR_VOTE = "clear_vote"
    STATE_SYNC = "state_sync"
    ACK = "ack"
    ERROR = "error"
    BROADCAST = "broadcast"


class BroadcastEventType(str, Enum):
    DRAW = "draw"
    STROKE_UNDONE = "stroke_undone"
    ANNOTATION = "annotation"
    ANNOTATION_REMOVED = "annotation_removed"
    CLEAR = "clear"
    CLEAR_PROPOSE = "clear_propose"
    CLEAR_REJECTED = "clear_rejected"
    CLEAR_PROPOSAL_CANCELLED = "clear_proposal_cancelled"
    CLEAR_PROPOSAL_EXPIRED = "clear_proposal_expired"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    ROOM_IDLE = "room_idle"
    ROOM_DESTROYED = "room_destroyed"


class ErrorCode(str, Enum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMIT = "RATE_LIMIT"
    USER_ALREADY_JOINED = "USER_ALREADY_JOINED"
    SEQUENCE_CONFLICT = "SEQUENCE_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CLEAR_REQUIRES_CONSENSUS = "CLEAR_REQUIRES_CONSENSUS"
    CLEAR_PROPOSAL_ACTIVE = "CLEAR_PROPOSAL_ACTIVE"
    CLEAR_PROPOSAL_NOT_FOUND = "CLEAR_PROPOSAL_NOT_FOUND"
    CLEAR_VOTE_DUPLICATE = "CLEAR_VOTE_DUPLICATE"
    ANNOTATION_NOT_FOUND = "ANNOTATION_NOT_FOUND"
    STROKE_NOT_FOUND = "STROKE_NOT_FOUND"


@dataclass
class Point:
    x: float
    y: float
    pressure: float


@dataclass
class Message:
    msg_id: str
    type: MessageType
    timestamp: int
    user_id: str
    room_id: str
    sequence_id: Optional[int]
    payload: JsonDict


@dataclass
class Event:
    sequence_id: int
    message: JsonDict


@dataclass
class BroadcastInstruction:
    room_id: str
    message: JsonDict
    exclude_user_id: Optional[str] = None


@dataclass
class HandlerResult:
    ack: JsonDict
    broadcasts: List[BroadcastInstruction] = field(default_factory=list)
    close_connection: bool = False
    post_actions: List[JsonDict] = field(default_factory=list)


@dataclass
class User:
    user_id: str
    user_name: str
    metadata: JsonDict = field(default_factory=dict)


@dataclass
class ClearProposalState:
    """In-memory consensus state for full canvas clear (not stored separately from Room)."""

    proposal_id: str
    proposer_id: str
    required_voters: Set[str]
    approvals: Set[str]
    expires_ms: int


@dataclass
class Room:
    room_id: str
    state: RoomState = RoomState.PENDING_INIT
    users: Set[str] = field(default_factory=set)
    user_metadata: Dict[str, JsonDict] = field(default_factory=dict)
    canvas_history: List[JsonDict] = field(default_factory=list)
    current_sequence: int = -1
    created_at: float = 0.0
    idle_deadline: Optional[float] = None
    pending_deadline: Optional[float] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    event_rate_bucket: Optional[Any] = field(default=None, repr=False)
    clear_proposal: Optional[ClearProposalState] = field(default=None, repr=False)
