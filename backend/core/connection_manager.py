"""
ConnectionManager

Owns WebSocket connection registry and message delivery.

Design goals (per frozen plan):
- register / unregister connections
- send (unicast) and broadcast (room-scoped)
- disconnect handling
- avoid tight coupling to FastAPI/Starlette by treating websocket as a duck-typed object:
  it may expose `send_json`, `send_text`, and `close`.

Integration contract:
- FastAPI layer should call `register(connection_id, websocket)` immediately on accept.
- After JOIN succeeds (in handler/router), FastAPI/handler should call `register(...)` again
  with `user_id` and `room_id` to bind the connection to identity and room.
  (register is idempotent and acts as an upsert/update.)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class _ConnEntry:
    connection_id: str
    websocket: Any
    user_id: Optional[str] = None
    room_id: Optional[str] = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    """
    In-memory connection registry for a single-process server.

    Public surface (frozen plan):
    - register(connection_id, websocket, user_id=None, room_id=None)
    - unregister(connection_id)
    - send(connection_id, message)
    - broadcast(room_id, message, exclude_user_id=None)
    - disconnect(connection_id, code=1000, reason=None)
    """

    def __init__(
        self,
        *,
        send_timeout_s: float = 3.0,
        close_timeout_s: float = 2.0,
    ) -> None:
        self._send_timeout_s = float(send_timeout_s)
        self._close_timeout_s = float(close_timeout_s)

        self._lock = asyncio.Lock()
        self._connections: Dict[str, _ConnEntry] = {}
        self._room_index: Dict[str, Set[str]] = {}
        self._user_index: Dict[str, str] = {}

    async def is_connection_id_taken(self, connection_id: str) -> bool:
        async with self._lock:
            return connection_id in self._connections

    async def register(
        self,
        connection_id: str,
        websocket: Any = None,
        *,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> None:
        """
        Register a websocket under connection_id.

        Idempotent: if connection_id already exists, updates websocket/user_id/room_id and
        updates the room index accordingly.
        """
        async with self._lock:
            prev = self._connections.get(connection_id)
            prev_room = prev.room_id if prev else None
            prev_user = prev.user_id if prev else None

            if prev is None and websocket is None:
                raise ValueError("websocket is required when registering a new connection")

            entry = prev or _ConnEntry(connection_id=connection_id, websocket=websocket)
            if websocket is not None:
                entry.websocket = websocket
            if user_id is not None:
                if prev_user and prev_user != user_id:
                    self._user_index.pop(prev_user, None)
                entry.user_id = user_id
                self._user_index[user_id] = connection_id
            if room_id is not None:
                entry.room_id = room_id
            self._connections[connection_id] = entry

            # Update room index if room_id changed.
            new_room = entry.room_id
            if prev_room and prev_room != new_room:
                ids = self._room_index.get(prev_room)
                if ids:
                    ids.discard(connection_id)
                    if not ids:
                        self._room_index.pop(prev_room, None)
            if new_room:
                self._room_index.setdefault(new_room, set()).add(connection_id)

    async def unregister(self, connection_id: str) -> None:
        async with self._lock:
            entry = self._connections.pop(connection_id, None)
            if not entry:
                return
            if entry.user_id and self._user_index.get(entry.user_id) == connection_id:
                self._user_index.pop(entry.user_id, None)
            if entry.room_id:
                ids = self._room_index.get(entry.room_id)
                if ids:
                    ids.discard(connection_id)
                    if not ids:
                        self._room_index.pop(entry.room_id, None)

    async def get_connection(self, connection_id: str) -> Optional[_ConnEntry]:
        # Used by higher layers in a pinch; not part of the frozen surface.
        async with self._lock:
            return self._connections.get(connection_id)

    async def get_connection_by_user(self, user_id: str) -> Optional[_ConnEntry]:
        async with self._lock:
            connection_id = self._user_index.get(user_id)
            if connection_id is None:
                return None
            return self._connections.get(connection_id)

    async def count_room_connections(self, room_id: str) -> int:
        async with self._lock:
            return len(self._room_index.get(room_id, set()))

    async def send(self, connection_id: str, message: Dict[str, Any]) -> bool:
        """
        Send a message to a specific connection.

        Returns True if sent, False if connection missing or send failed (connection will be
        unregistered on failure).
        """
        async with self._lock:
            entry = self._connections.get(connection_id)
        if not entry:
            return False

        async with entry.send_lock:
            try:
                await asyncio.wait_for(
                    self._send_via_websocket(entry.websocket, message),
                    timeout=self._send_timeout_s,
                )
                return True
            except Exception as e:  # noqa: BLE001 - treat as transport failure
                logger.info("send failed; dropping connection_id=%s err=%r", connection_id, e)
                await self.unregister(connection_id)
                return False

    async def broadcast(
        self,
        room_id: str,
        message: Dict[str, Any],
        *,
        exclude_user_id: Optional[str] = None,
    ) -> int:
        """
        Broadcast to all connections currently bound to room_id.

        Returns number of connections that successfully received the message.
        """
        async with self._lock:
            targets = list(self._room_index.get(room_id, set()))
            entries = [self._connections.get(cid) for cid in targets]

        # Filter out missing and excluded.
        filtered: list[str] = []
        for cid, entry in zip(targets, entries):
            if not entry:
                continue
            if exclude_user_id is not None and entry.user_id == exclude_user_id:
                continue
            filtered.append(cid)

        if not filtered:
            return 0

        results = await asyncio.gather(
            *(self.send(cid, message) for cid in filtered),
            return_exceptions=False,
        )
        return sum(1 for ok in results if ok)

    async def disconnect(
        self,
        connection_id: str,
        *,
        code: int = 1000,
        reason: Optional[str] = None,
    ) -> None:
        async with self._lock:
            entry = self._connections.get(connection_id)

        if entry:
            try:
                close = getattr(entry.websocket, "close", None)
                if callable(close):
                    await asyncio.wait_for(close(code=code, reason=reason), timeout=self._close_timeout_s)
            except Exception:  # noqa: BLE001
                # Closing is best-effort.
                pass
        await self.unregister(connection_id)

    async def disconnect_room(self, room_id: str, *, code: int = 1001, reason: Optional[str] = None) -> None:
        # Convenience for future use; not part of frozen surface.
        async with self._lock:
            cids = list(self._room_index.get(room_id, set()))
        await asyncio.gather(*(self.disconnect(cid, code=code, reason=reason) for cid in cids))

    async def _send_via_websocket(self, websocket: Any, message: Dict[str, Any]) -> None:
        send_json = getattr(websocket, "send_json", None)
        if callable(send_json):
            await send_json(message)
            return

        send_text = getattr(websocket, "send_text", None)
        if callable(send_text):
            await send_text(json.dumps(message, separators=(",", ":"), ensure_ascii=True))
            return

        # Fall back to common "send" method used by some websocket libs.
        send = getattr(websocket, "send", None)
        if callable(send):
            await send(json.dumps(message, separators=(",", ":"), ensure_ascii=True))
            return

        raise TypeError("websocket does not support send_json/send_text/send")
