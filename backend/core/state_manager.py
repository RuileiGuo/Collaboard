"""
State machine layer for CollabBoard backend.

Owned by Worker B (Backend-StateManager).

This module intentionally contains no WebSocket IO. It provides:
- User state transitions (8 states) and action validation
- Room state transition validation (4 states)
- Time/deadline helpers and polling-style timeout application

It depends only on backend.core.models and backend.config (best-effort).
If those symbols do not exist yet (other workers are creating them in parallel),
we fall back to local enums/defaults so imports and unit tests can run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple


# --- Best-effort imports (Core Contract is implemented by another worker) ---
try:  # pragma: no cover - exercised once core models land
    from backend.core.models import UserState as UserState  # type: ignore
    from backend.core.models import RoomState as RoomState  # type: ignore
    from backend.core.models import MessageType as MessageType  # type: ignore
except Exception:  # pragma: no cover
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


def _now_s(now: Optional[float] = None) -> float:
    return time.time() if now is None else float(now)


def _read_config_seconds(attr: str, default: float) -> float:
    """
    Read an integer/float seconds value from backend.config if present.
    We keep this loose to avoid hard-coupling to config shape while other workers
    are still scaffolding it.
    """
    try:  # pragma: no cover - config not yet in repo at the time of writing
        import backend.config as cfg  # type: ignore

        value = getattr(cfg, attr, default)
        return float(value)
    except Exception:
        return float(default)


# Defaults are derived from 02_STATE_MACHINE_DESIGN.md
JOIN_GRACE_SECONDS = _read_config_seconds("USER_JOIN_GRACE_SECONDS", 30.0)
JOINED_IDLE_SECONDS = _read_config_seconds("USER_JOINED_IDLE_SECONDS", 60.0)
ACTIVE_IDLE_SECONDS = _read_config_seconds("USER_ACTIVE_IDLE_SECONDS", 180.0)
IDLE_TIMEOUT_SECONDS = _read_config_seconds("USER_IDLE_TIMEOUT_SECONDS", 180.0)
LEFT_DISCONNECT_SECONDS = _read_config_seconds("USER_LEFT_DISCONNECT_SECONDS", 5.0)


class StateManagerError(RuntimeError):
    pass


class UnknownUserError(StateManagerError):
    pass


class InvalidUserStateTransition(StateManagerError):
    pass


class InvalidRoomStateTransition(StateManagerError):
    pass


@dataclass(frozen=True)
class UserDeadlines:
    join_by: Optional[float] = None
    idle_by: Optional[float] = None
    timeout_by: Optional[float] = None
    disconnect_by: Optional[float] = None


@dataclass
class UserSession:
    user_id: str
    state: UserState = UserState.INIT
    connection_id: Optional[str] = None
    room_id: Optional[str] = None

    connected_at: Optional[float] = None
    last_activity_at: Optional[float] = None
    idle_since: Optional[float] = None
    left_at: Optional[float] = None


@dataclass(frozen=True)
class TransitionEvent:
    """
    State transition report that higher layers can turn into side effects.
    No IO is performed here.
    """

    entity: str  # "user" or "room"
    entity_id: str
    from_state: str
    to_state: str
    reason: str


class StateManager:
    """
    Thread-safe in-memory state manager.

    Note: The websocket loop / router is expected to call:
    - on_connected(user_id, connection_id)
    - validate_user_action(user_id, message_type)
    - on_join / on_activity / on_leave / on_disconnect
    - apply_timeouts() periodically (or before handling a message)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._users: Dict[str, UserSession] = {}

    # --- User helpers ---
    def get_or_create_user(self, user_id: str) -> UserSession:
        with self._lock:
            sess = self._users.get(user_id)
            if sess is None:
                sess = UserSession(user_id=user_id)
                self._users[user_id] = sess
            return sess

    def get_user(self, user_id: str) -> UserSession:
        with self._lock:
            sess = self._users.get(user_id)
            if sess is None:
                raise UnknownUserError(f"Unknown user_id={user_id}")
            return sess

    def get_user_state(self, user_id: str) -> UserState:
        return self.get_user(user_id).state

    # --- Deadlines ---
    def get_user_deadlines(self, user_id: str, now: Optional[float] = None) -> UserDeadlines:
        now_s = _now_s(now)
        with self._lock:
            sess = self.get_user(user_id)
            if sess.state == UserState.CONNECTED and sess.connected_at is not None:
                return UserDeadlines(join_by=sess.connected_at + JOIN_GRACE_SECONDS)

            if sess.state in (UserState.JOINED, UserState.ACTIVE):
                base = sess.last_activity_at if sess.last_activity_at is not None else now_s
                idle_after = JOINED_IDLE_SECONDS if sess.state == UserState.JOINED else ACTIVE_IDLE_SECONDS
                return UserDeadlines(idle_by=base + idle_after)

            if sess.state == UserState.IDLE and sess.idle_since is not None:
                return UserDeadlines(timeout_by=sess.idle_since + IDLE_TIMEOUT_SECONDS)

            if sess.state == UserState.LEFT and sess.left_at is not None:
                return UserDeadlines(disconnect_by=sess.left_at + LEFT_DISCONNECT_SECONDS)

            return UserDeadlines()

    # --- Public API (frozen plan) ---
    def on_connected(
        self,
        user_id: str,
        connection_id: Optional[str] = None,
        now: Optional[float] = None,
    ) -> List[TransitionEvent]:
        now_s = _now_s(now)
        with self._lock:
            sess = self.get_or_create_user(user_id)
            prev = sess.state
            # Allow reconnect to overwrite prior session state.
            sess.state = UserState.CONNECTED
            sess.connection_id = connection_id
            sess.room_id = None
            sess.connected_at = now_s
            sess.last_activity_at = now_s
            sess.idle_since = None
            sess.left_at = None
            if prev != UserState.CONNECTED:
                return [
                    TransitionEvent(
                        entity="user",
                        entity_id=user_id,
                        from_state=str(prev),
                        to_state=str(sess.state),
                        reason="connected",
                    )
                ]
            return []

    def on_join(self, user_id: str, room_id: str, now: Optional[float] = None) -> List[TransitionEvent]:
        now_s = _now_s(now)
        with self._lock:
            sess = self.get_or_create_user(user_id)
            if sess.state != UserState.CONNECTED:
                raise InvalidUserStateTransition(
                    f"JOIN not allowed in state={sess.state} user_id={user_id}"
                )
            prev = sess.state
            sess.state = UserState.JOINED
            sess.room_id = room_id
            sess.last_activity_at = now_s
            sess.idle_since = None
            return [
                TransitionEvent(
                    entity="user",
                    entity_id=user_id,
                    from_state=str(prev),
                    to_state=str(sess.state),
                    reason="join",
                )
            ]

    def on_activity(
        self,
        user_id: str,
        now: Optional[float] = None,
        message_type: Optional[MessageType] = None,
    ) -> List[TransitionEvent]:
        """
        Record any meaningful activity (DRAW/CLEAR/STATE_SYNC; can also be used for JOIN ack etc).
        This may promote JOINED->ACTIVE or IDLE->ACTIVE.
        """
        now_s = _now_s(now)
        with self._lock:
            sess = self.get_user(user_id)
            prev = sess.state
            if sess.state == UserState.JOINED:
                sess.state = UserState.ACTIVE
                sess.idle_since = None
            elif sess.state == UserState.IDLE:
                sess.state = UserState.ACTIVE
                sess.idle_since = None
            elif sess.state == UserState.ACTIVE:
                pass
            else:
                # CONNECTED/LEFT/TIMEOUT/DISCONNECTED should not be marked active.
                raise InvalidUserStateTransition(
                    f"Activity not allowed in state={sess.state} user_id={user_id} message_type={message_type}"
                )
            sess.last_activity_at = now_s
            if prev != sess.state:
                return [
                    TransitionEvent(
                        entity="user",
                        entity_id=user_id,
                        from_state=str(prev),
                        to_state=str(sess.state),
                        reason="activity",
                    )
                ]
            return []

    def on_leave(self, user_id: str, now: Optional[float] = None) -> List[TransitionEvent]:
        now_s = _now_s(now)
        with self._lock:
            sess = self.get_user(user_id)
            if sess.state not in (UserState.JOINED, UserState.ACTIVE, UserState.IDLE):
                raise InvalidUserStateTransition(
                    f"LEAVE not allowed in state={sess.state} user_id={user_id}"
                )
            prev = sess.state
            sess.state = UserState.LEFT
            sess.room_id = None
            sess.left_at = now_s
            sess.idle_since = None
            return [
                TransitionEvent(
                    entity="user",
                    entity_id=user_id,
                    from_state=str(prev),
                    to_state=str(sess.state),
                    reason="leave",
                )
            ]

    def on_disconnect(self, user_id: str, now: Optional[float] = None) -> List[TransitionEvent]:
        _ = _now_s(now)
        with self._lock:
            sess = self.get_or_create_user(user_id)
            prev = sess.state
            sess.state = UserState.DISCONNECTED
            sess.connection_id = None
            sess.room_id = None
            sess.idle_since = None
            sess.left_at = None
            return [
                TransitionEvent(
                    entity="user",
                    entity_id=user_id,
                    from_state=str(prev),
                    to_state=str(sess.state),
                    reason="disconnect",
                )
            ]

    def on_timeout(self, user_id: str, now: Optional[float] = None) -> List[TransitionEvent]:
        """
        TIMEOUT is modeled as an intermediate state, but per design it transitions to DISCONNECTED immediately.
        """
        _ = _now_s(now)
        with self._lock:
            sess = self.get_or_create_user(user_id)
            events: List[TransitionEvent] = []
            prev = sess.state
            if sess.state != UserState.TIMEOUT:
                sess.state = UserState.TIMEOUT
                events.append(
                    TransitionEvent(
                        entity="user",
                        entity_id=user_id,
                        from_state=str(prev),
                        to_state=str(sess.state),
                        reason="timeout",
                    )
                )
            # Immediate disconnect
            events.extend(self.on_disconnect(user_id, now=now))
            return events

    def validate_user_action(self, user_id: str, message_type: MessageType) -> bool:
        """
        Validate whether a user is allowed to send a given message type in current state.
        This is intended to be called by MessageRouter before delegating to handlers.
        """
        with self._lock:
            sess = self._users.get(user_id)
            if sess is None:
                # Router may call this before on_connected; treat as not allowed.
                return False
            st = sess.state

            mt = str(message_type)
            # Normalize common enums/string values.
            if hasattr(message_type, "value"):
                mt = str(getattr(message_type, "value"))

            if st == UserState.CONNECTED:
                return mt in (str(getattr(MessageType, "JOIN", "join")), "join")
            if st in (UserState.JOINED, UserState.ACTIVE, UserState.IDLE):
                allowed = {
                    str(getattr(MessageType, "DRAW", "draw")),
                    str(getattr(MessageType, "ANNOTATION", "annotation")),
                    str(getattr(MessageType, "ANNOTATION_DELETE", "annotation_delete")),
                    str(getattr(MessageType, "ANNOTATION_RESTORE", "annotation_restore")),
                    str(getattr(MessageType, "DRAW_UNDO", "draw_undo")),
                    str(getattr(MessageType, "DRAW_REDO", "draw_redo")),
                    str(getattr(MessageType, "CLEAR", "clear")),
                    str(getattr(MessageType, "CLEAR_PROPOSE", "clear_propose")),
                    str(getattr(MessageType, "CLEAR_VOTE", "clear_vote")),
                    str(getattr(MessageType, "LEAVE", "leave")),
                    str(getattr(MessageType, "STATE_SYNC", "state_sync")),
                    "draw",
                    "annotation",
                    "annotation_delete",
                    "annotation_restore",
                    "draw_undo",
                    "draw_redo",
                    "clear",
                    "clear_propose",
                    "clear_vote",
                    "leave",
                    "state_sync",
                }
                return mt in allowed
            # LEFT/TIMEOUT/DISCONNECTED/INIT: disallow client actions.
            return False

    # --- Timeout polling ---
    def apply_timeouts(self, now: Optional[float] = None) -> List[TransitionEvent]:
        """
        Apply all due automatic transitions based on deadlines and return transition events.

        Higher layers can decide what to do with these events (e.g. instruct ConnectionManager to disconnect).
        """
        now_s = _now_s(now)
        events: List[TransitionEvent] = []
        with self._lock:
            for user_id, sess in list(self._users.items()):
                st = sess.state

                if st == UserState.CONNECTED and sess.connected_at is not None:
                    if now_s >= sess.connected_at + JOIN_GRACE_SECONDS:
                        prev = sess.state
                        sess.state = UserState.DISCONNECTED
                        sess.connection_id = None
                        sess.room_id = None
                        events.append(
                            TransitionEvent(
                                entity="user",
                                entity_id=user_id,
                                from_state=str(prev),
                                to_state=str(sess.state),
                                reason="join_timeout",
                            )
                        )
                    continue

                if st in (UserState.JOINED, UserState.ACTIVE):
                    base = sess.last_activity_at if sess.last_activity_at is not None else now_s
                    idle_after = JOINED_IDLE_SECONDS if st == UserState.JOINED else ACTIVE_IDLE_SECONDS
                    if now_s >= base + idle_after:
                        prev = sess.state
                        sess.state = UserState.IDLE
                        sess.idle_since = now_s
                        events.append(
                            TransitionEvent(
                                entity="user",
                                entity_id=user_id,
                                from_state=str(prev),
                                to_state=str(sess.state),
                                reason="idle_timeout",
                            )
                        )
                    continue

                if st == UserState.IDLE and sess.idle_since is not None:
                    if now_s >= sess.idle_since + IDLE_TIMEOUT_SECONDS:
                        # TIMEOUT then immediate DISCONNECTED
                        prev = sess.state
                        sess.state = UserState.TIMEOUT
                        events.append(
                            TransitionEvent(
                                entity="user",
                                entity_id=user_id,
                                from_state=str(prev),
                                to_state=str(sess.state),
                                reason="idle_expired",
                            )
                        )
                        prev2 = sess.state
                        sess.state = UserState.DISCONNECTED
                        sess.connection_id = None
                        sess.room_id = None
                        events.append(
                            TransitionEvent(
                                entity="user",
                                entity_id=user_id,
                                from_state=str(prev2),
                                to_state=str(sess.state),
                                reason="disconnect_after_timeout",
                            )
                        )
                    continue

                if st == UserState.LEFT and sess.left_at is not None:
                    if now_s >= sess.left_at + LEFT_DISCONNECT_SECONDS:
                        prev = sess.state
                        sess.state = UserState.DISCONNECTED
                        sess.connection_id = None
                        events.append(
                            TransitionEvent(
                                entity="user",
                                entity_id=user_id,
                                from_state=str(prev),
                                to_state=str(sess.state),
                                reason="left_grace_elapsed",
                            )
                        )
                    continue

        return events

    # --- Room transition validation (frozen plan) ---
    def validate_room_transition(self, room_state: RoomState, event: str) -> bool:
        try:
            _ = self.next_room_state(room_state, event)
            return True
        except InvalidRoomStateTransition:
            return False

    def next_room_state(self, room_state: RoomState, event: str) -> RoomState:
        """
        Room state machine (4 states):
        - PENDING_INIT -> ACTIVE (join)
        - ACTIVE -> IDLE (leave_last)
        - IDLE -> ACTIVE (join)
        - IDLE -> DESTROYED (ttl_expired)
        - ACTIVE -> DESTROYED (destroy) [explicit destroy]
        - PENDING_INIT -> DESTROYED (destroy) [explicit destroy]
        - DESTROYED: terminal
        """
        rs = str(room_state.value) if hasattr(room_state, "value") else str(room_state)
        ev = str(event)

        # Normalize known state strings to simplify compatibility with either Enum values or names.
        def _rs_is(name: str) -> bool:
            return rs == name or rs.lower() == name.lower()

        if _rs_is("destroyed"):
            raise InvalidRoomStateTransition(f"Room already destroyed; event={event}")

        if _rs_is("pending_init") or _rs_is("empty"):
            if ev in ("join", "user_joined"):
                return getattr(RoomState, "ACTIVE", RoomState.ACTIVE)
            if ev in ("destroy", "ttl_expired"):
                return getattr(RoomState, "DESTROYED", RoomState.DESTROYED)
            raise InvalidRoomStateTransition(f"Invalid event={event} for room_state={room_state}")

        if _rs_is("active"):
            if ev in ("draw", "clear", "join", "user_joined", "leave_non_last", "user_left"):
                return getattr(RoomState, "ACTIVE", RoomState.ACTIVE)
            if ev in ("leave_last", "room_idle"):
                return getattr(RoomState, "IDLE", RoomState.IDLE)
            if ev in ("destroy",):
                return getattr(RoomState, "DESTROYED", RoomState.DESTROYED)
            # ttl_expired is not expected while ACTIVE (TTL starts on idle)
            raise InvalidRoomStateTransition(f"Invalid event={event} for room_state={room_state}")

        if _rs_is("idle"):
            if ev in ("join", "user_joined"):
                return getattr(RoomState, "ACTIVE", RoomState.ACTIVE)
            if ev in ("ttl_expired", "destroy", "room_destroyed"):
                return getattr(RoomState, "DESTROYED", RoomState.DESTROYED)
            raise InvalidRoomStateTransition(f"Invalid event={event} for room_state={room_state}")

        # Unknown/unsupported room state
        raise InvalidRoomStateTransition(f"Unknown room_state={room_state} event={event}")
