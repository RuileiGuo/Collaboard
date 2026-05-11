"""Room lifecycle and event history management."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend import config
from backend.core.models import BroadcastEventType, ClearProposalState, Room, RoomState
from backend.utils.exceptions import RoomEventRateLimitError, RoomNotFoundError, UserAlreadyJoinedError
from backend.utils.rate_limit import TokenBucket

if TYPE_CHECKING:
    from backend.handlers.error_handler import ErrorBuilder


class RoomManager:
    def __init__(
        self,
        *,
        room_idle_ttl_seconds: int = config.ROOM_IDLE_TTL_SECONDS,
        room_pending_ttl_seconds: int = config.ROOM_PENDING_INIT_TTL_SECONDS,
        room_event_rate_capacity: int = config.ROOM_RATE_LIMIT_EVENTS_PER_SECOND,
        room_event_rate_refill_per_sec: float = float(config.ROOM_RATE_LIMIT_EVENTS_PER_SECOND),
    ) -> None:
        self._room_idle_ttl_seconds = int(room_idle_ttl_seconds)
        self._room_pending_ttl_seconds = int(room_pending_ttl_seconds)
        self._room_event_rate_capacity = int(room_event_rate_capacity)
        self._room_event_rate_refill_per_sec = float(room_event_rate_refill_per_sec)
        self._lock = asyncio.Lock()
        self._rooms: Dict[str, Room] = {}

    async def get(self, room_id: str) -> Optional[Room]:
        async with self._lock:
            return self._rooms.get(room_id)

    async def get_or_create(self, room_id: str) -> Room:
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                now = time.time()
                room = Room(
                    room_id=room_id,
                    created_at=now,
                    pending_deadline=now + self._room_pending_ttl_seconds,
                )
                self._rooms[room_id] = room
            return room

    async def join(
        self,
        room_id: str,
        user_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Room:
        room = await self.get_or_create(room_id)
        async with room.lock:
            if room.state == RoomState.DESTROYED:
                raise RoomNotFoundError(room_id)
            if user_id in room.users:
                raise UserAlreadyJoinedError(user_id, room_id)
            room.users.add(user_id)
            room.user_metadata[user_id] = dict(metadata or {})
            room.idle_deadline = None
            room.pending_deadline = None
            room.state = RoomState.ACTIVE
            return room

    async def leave(self, room_id: str, user_id: str) -> Room:
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        async with room.lock:
            room.users.discard(user_id)
            room.user_metadata.pop(user_id, None)
            if room.users:
                room.state = RoomState.ACTIVE
                room.idle_deadline = None
            else:
                room.state = RoomState.IDLE
                room.idle_deadline = time.time() + self._room_idle_ttl_seconds
            return room

    async def is_user_in_room(self, room_id: str, user_id: str) -> bool:
        room = await self.get(room_id)
        if room is None:
            return False
        async with room.lock:
            return user_id in room.users

    async def annotation_visible_and_author(self, room_id: str, annotation_id: str) -> tuple[bool, Optional[str]]:
        """
        Scan canvas_history in order: last event for this annotation_id wins.
        Returns (visible, author_user_id) where author is set only when visible.
        """
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        visible = False
        author: Optional[str] = None
        async with room.lock:
            for ev in room.canvas_history:
                p = ev.get("payload") or {}
                et = p.get("event_type")
                aid = p.get("annotation_id")
                if aid != annotation_id:
                    continue
                if et == BroadcastEventType.ANNOTATION.value:
                    visible = True
                    author = str(ev.get("user_id", ""))
                elif et == BroadcastEventType.ANNOTATION_REMOVED.value:
                    visible = False
                    author = None
        return visible, author

    async def stroke_visible_and_author(self, room_id: str, stroke_id: str) -> tuple[bool, Optional[str]]:
        """
        Scan canvas_history: last draw or stroke_undone for this stroke_id wins.
        Returns (visible, author_user_id) where author is set only when visible.
        """
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        visible = False
        author: Optional[str] = None
        async with room.lock:
            for ev in room.canvas_history:
                p = ev.get("payload") or {}
                et = p.get("event_type")
                sid = p.get("stroke_id")
                if sid != stroke_id:
                    continue
                if et == BroadcastEventType.DRAW.value:
                    visible = True
                    author = str(ev.get("user_id", ""))
                elif et == BroadcastEventType.STROKE_UNDONE.value:
                    visible = False
                    author = None
        return visible, author

    async def draw_redo_stroke_payload(
        self, room_id: str, stroke_id: str, requester: str
    ) -> Optional[Dict[str, Any]]:
        """
        If the last event for stroke_id is stroke_undone, return draw payload fields
        from the draw event immediately before that undo (author must be requester).
        """
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        async with room.lock:
            history = room.canvas_history
            last_undone_idx: Optional[int] = None
            for i in range(len(history) - 1, -1, -1):
                ev = history[i]
                p = ev.get("payload") or {}
                if p.get("stroke_id") != stroke_id:
                    continue
                et = p.get("event_type")
                if et == BroadcastEventType.STROKE_UNDONE.value:
                    last_undone_idx = i
                    break
                if et == BroadcastEventType.DRAW.value:
                    return None
            if last_undone_idx is None:
                return None
            for j in range(last_undone_idx - 1, -1, -1):
                ev = history[j]
                p = ev.get("payload") or {}
                if p.get("event_type") != BroadcastEventType.DRAW.value or p.get("stroke_id") != stroke_id:
                    continue
                if str(ev.get("user_id", "")) != requester:
                    return None
                return {
                    "stroke_id": p["stroke_id"],
                    "tool": p["tool"],
                    "color": p["color"],
                    "width": p["width"],
                    "points": p["points"],
                }
        return None

    async def annotation_restore_fields(
        self, room_id: str, annotation_id: str, requester: str
    ) -> Optional[Dict[str, Any]]:
        """
        If the annotation is currently removed and `requester` issued that removal,
        return payload fields for a new `annotation` broadcast (no event_type key).
        """
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        visible = False
        last_fields: Optional[Dict[str, Any]] = None
        last_remover: Optional[str] = None
        async with room.lock:
            for ev in room.canvas_history:
                p = ev.get("payload") or {}
                if p.get("annotation_id") != annotation_id:
                    continue
                et = p.get("event_type")
                if et == BroadcastEventType.ANNOTATION.value:
                    visible = True
                    last_fields = {
                        "annotation_id": p["annotation_id"],
                        "mode": p["mode"],
                        "content": p["content"],
                        "x": p["x"],
                        "y": p["y"],
                        "font_size": p["font_size"],
                        "color": p["color"],
                    }
                elif et == BroadcastEventType.ANNOTATION_REMOVED.value:
                    visible = False
                    last_remover = str(ev.get("user_id", ""))
        if visible or last_fields is None or last_remover != requester:
            return None
        return last_fields

    async def get_user_display_name(self, room_id: str, user_id: str) -> str:
        """Resolved display name from join metadata (for broadcast payloads)."""
        room = await self.get(room_id)
        if room is None:
            return user_id
        async with room.lock:
            meta = room.user_metadata.get(user_id, {})
            return str(meta.get("user_name", user_id))

    async def issue_sequence(self, room_id: str) -> int:
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        async with room.lock:
            room.current_sequence += 1
            return room.current_sequence

    async def append_event(self, room_id: str, message: Dict[str, Any]) -> int:
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        async with room.lock:
            if room.event_rate_bucket is None:
                room.event_rate_bucket = TokenBucket(
                    self._room_event_rate_capacity,
                    self._room_event_rate_refill_per_sec,
                )
            if not room.event_rate_bucket.consume(1.0):
                raise RoomEventRateLimitError(room_id)
            room.current_sequence += 1
            sequence_id = room.current_sequence
            message["sequence_id"] = sequence_id
            event_type = message.get("payload", {}).get("event_type")
            if event_type == BroadcastEventType.CLEAR.value:
                room.canvas_history.clear()
            room.canvas_history.append(message.copy())
            return sequence_id

    async def get_snapshot(self, room_id: str) -> Dict[str, Any]:
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        async with room.lock:
            active_users = [
                {
                    "user_id": user_id,
                    "user_name": room.user_metadata.get(user_id, {}).get("user_name", user_id),
                }
                for user_id in sorted(room.users)
            ]
            return {
                "room_id": room.room_id,
                "current_sequence": room.current_sequence,
                "user_count": len(room.users),
                "canvas_history": [event.copy() for event in room.canvas_history],
                "active_users": active_users,
            }

    async def get_events_since(self, room_id: str, last_sequence: int) -> List[Dict[str, Any]]:
        room = await self.get(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        async with room.lock:
            return [
                event.copy()
                for event in room.canvas_history
                if int(event.get("sequence_id", -1)) > last_sequence
            ]

    async def find_room_for_user(self, user_id: str) -> Optional[str]:
        async with self._lock:
            rooms = list(self._rooms.values())
        for room in rooms:
            async with room.lock:
                if user_id in room.users:
                    return room.room_id
        return None

    async def destroy(self, room_id: str) -> Optional[Room]:
        async with self._lock:
            room = self._rooms.pop(room_id, None)
        if room is None:
            return None
        async with room.lock:
            room.state = RoomState.DESTROYED
            room.users.clear()
            room.user_metadata.clear()
            room.idle_deadline = None
            room.pending_deadline = None
            room.clear_proposal = None
        return room

    async def pop_expired_clear_proposal_broadcast_if_any(
        self, room_id: str, now_ms: int, error_builder: "ErrorBuilder"
    ) -> Optional[Dict[str, Any]]:
        room = await self.get(room_id)
        if room is None:
            return None
        proposal_id: Optional[str] = None
        async with room.lock:
            cp = room.clear_proposal
            if cp is None or now_ms < cp.expires_ms:
                return None
            room.clear_proposal = None
            proposal_id = cp.proposal_id
        return error_builder.build_broadcast(
            str(uuid.uuid4()),
            room_id,
            "server",
            payload={
                "event_type": BroadcastEventType.CLEAR_PROPOSAL_EXPIRED.value,
                "room_id": room_id,
                "proposal_id": proposal_id,
            },
            now_ms=now_ms,
        )

    async def sweep_expired_clear_proposals(
        self, now_ms: int, error_builder: "ErrorBuilder"
    ) -> List[tuple[str, Dict[str, Any]]]:
        async with self._lock:
            room_ids = [r.room_id for r in self._rooms.values()]
        out: List[tuple[str, Dict[str, Any]]] = []
        for rid in room_ids:
            msg = await self.pop_expired_clear_proposal_broadcast_if_any(rid, now_ms, error_builder)
            if msg is not None:
                out.append((rid, msg))
        return out

    async def collect_clear_proposal_messages_on_user_exit(
        self,
        room_id: str,
        exiting_user_id: str,
        error_builder: "ErrorBuilder",
        now_ms: int,
    ) -> List[Dict[str, Any]]:
        """
        Before removing a user from a room, reconcile any active clear proposal.
        Returns 0..1 broadcast dicts to append_event + room broadcast (caller sends).
        """
        room = await self.get(room_id)
        if room is None:
            return []
        cp_snapshot: Optional[ClearProposalState] = None
        cancel = False
        execute_clear = False
        proposer_for_clear: Optional[str] = None
        async with room.lock:
            cp = room.clear_proposal
            if cp is None:
                return []
            if cp.proposer_id == exiting_user_id:
                room.clear_proposal = None
                cancel = True
                cp_snapshot = cp
            else:
                cp.required_voters.discard(exiting_user_id)
                if cp.required_voters <= cp.approvals:
                    proposer_for_clear = cp.proposer_id
                    room.clear_proposal = None
                    execute_clear = True
                    cp_snapshot = cp
        if cancel and cp_snapshot:
            return [
                error_builder.build_broadcast(
                    str(uuid.uuid4()),
                    room_id,
                    "server",
                    payload={
                        "event_type": BroadcastEventType.CLEAR_PROPOSAL_CANCELLED.value,
                        "room_id": room_id,
                        "proposal_id": cp_snapshot.proposal_id,
                        "reason": "proposer_left",
                    },
                    now_ms=now_ms,
                )
            ]
        if execute_clear and proposer_for_clear and cp_snapshot:
            uname = await self.get_user_display_name(room_id, proposer_for_clear)
            return [
                error_builder.build_broadcast(
                    str(uuid.uuid4()),
                    room_id,
                    proposer_for_clear,
                    payload={
                        "event_type": BroadcastEventType.CLEAR.value,
                        "user_id": proposer_for_clear,
                        "user_name": uname,
                        "clear_type": "full",
                        "consensus": True,
                        "proposal_id": cp_snapshot.proposal_id,
                    },
                    now_ms=now_ms,
                )
            ]
        return []

    async def expire_rooms(self, *, now: Optional[float] = None) -> List[str]:
        current = time.time() if now is None else float(now)
        async with self._lock:
            rooms = list(self._rooms.values())

        expired_ids: List[str] = []
        for room in rooms:
            async with room.lock:
                should_destroy = (
                    room.state == RoomState.PENDING_INIT
                    and room.pending_deadline is not None
                    and current >= room.pending_deadline
                ) or (
                    room.state == RoomState.IDLE
                    and room.idle_deadline is not None
                    and current >= room.idle_deadline
                )
            if should_destroy:
                await self.destroy(room.room_id)
                expired_ids.append(room.room_id)
        return expired_ids
