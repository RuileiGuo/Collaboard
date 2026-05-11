"""
Message router for CollabBoard backend.

Worker-D owned module.

Design goals (from frozen plan):
- Parse JSON, enforce base invariants (size, timestamp tolerance, required fields)
- Optional JSON-schema validation hook (implemented in Worker-A core contract)
- Dedup cache (msg_id -> ACK/ERROR) with TTL; duplicates replay sender response only
- Token-bucket rate limiting (per connection_id)
- Route to per-message handlers (join/leave/draw/clear/state_sync)

This module intentionally does NOT import concrete handlers to avoid circular imports.
FastAPI integration (Worker-E) should instantiate handlers and pass them in.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Mapping, MutableMapping, Optional, Protocol

from backend.handlers.error_handler import ErrorBuilder, ErrorCode
from backend.utils.exceptions import RoomEventRateLimitError


JsonDict = Dict[str, Any]


class SchemaValidator(Protocol):
    def __call__(self, message: Mapping[str, Any]) -> None: ...


class MessageHandler(Protocol):
    async def handle(self, ctx: "HandlerContext", message: Mapping[str, Any]) -> "HandlerResult": ...


@dataclass(frozen=True)
class RouterConfig:
    max_message_bytes: int = 64 * 1024
    timestamp_tolerance_sec: int = 30
    dedup_ttl_sec: int = 300
    rate_capacity: int = 20
    rate_refill_per_sec: float = 10.0


@dataclass
class HandlerContext:
    connection_id: str
    connection_manager: Any
    room_manager: Any
    state_manager: Any
    error_builder: ErrorBuilder
    now_ms: int
    config: RouterConfig


@dataclass
class HandlerResult:
    """
    Contract between Router and FastAPI loop.

    - ack: the single sender reply (ACK or ERROR) to be sent back to the origin connection.
    - broadcasts: 0..N server->room broadcasts to be sent by integration layer.
    - close_connection: indicates integration should close the websocket.
    - post_actions: side effects for integration/managers (TTL timers, destroys, etc.)
    """

    ack: JsonDict
    broadcasts: list[JsonDict] = field(default_factory=list)
    close_connection: bool = False
    post_actions: list[JsonDict] = field(default_factory=list)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_client_timestamp_ms(ts_value: Any) -> Optional[int]:
    """
    Accept seconds or milliseconds. Return normalized milliseconds int, else None.
    """

    if ts_value is None:
        return None
    if isinstance(ts_value, bool):
        return None
    if isinstance(ts_value, (int, float)):
        ts = int(ts_value)
        # Heuristic: seconds timestamps are typically 10 digits, ms are 13.
        if ts < 10_000_000_000:
            ts *= 1000
        return ts
    return None


class _DedupCache:
    def __init__(self, ttl_sec: int) -> None:
        self._ttl_sec = ttl_sec
        self._store: MutableMapping[str, tuple[float, JsonDict]] = {}

    def get(self, msg_id: str) -> Optional[JsonDict]:
        now = time.time()
        entry = self._store.get(msg_id)
        if entry is None:
            return None
        expires_at, response = entry
        if now >= expires_at:
            self._store.pop(msg_id, None)
            return None
        return response

    def set(self, msg_id: str, response: JsonDict) -> None:
        expires_at = time.time() + self._ttl_sec
        self._store[msg_id] = (expires_at, response)


class _TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self.tokens = float(capacity)
        self.last_ts = time.time()

    def consume(self, amount: float = 1.0) -> bool:
        now = time.time()
        elapsed = now - self.last_ts
        self.last_ts = now
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class MessageRouter:
    CLIENT_TYPES = {
        "join",
        "leave",
        "draw",
        "annotation",
        "annotation_delete",
        "annotation_restore",
        "draw_undo",
        "draw_redo",
        "clear",
        "clear_propose",
        "clear_vote",
        "state_sync",
    }

    def __init__(
        self,
        *,
        handlers: Mapping[str, MessageHandler],
        connection_manager: Any,
        room_manager: Any,
        state_manager: Any,
        config: Optional[RouterConfig] = None,
        schema_validator: Optional[SchemaValidator] = None,
        error_builder: Optional[ErrorBuilder] = None,
    ) -> None:
        self._handlers = dict(handlers)
        self._connection_manager = connection_manager
        self._room_manager = room_manager
        self._state_manager = state_manager
        self._config = config or RouterConfig()
        self._schema_validator = schema_validator
        self._error_builder = error_builder or ErrorBuilder()

        self._dedup = _DedupCache(ttl_sec=self._config.dedup_ttl_sec)
        self._buckets: MutableMapping[str, _TokenBucket] = {}

    async def handle_raw(self, raw: Any, *, connection_id: str) -> HandlerResult:
        """
        Parse + validate + route a raw websocket message.
        Returns a HandlerResult whose .ack must be sent back to the sender.
        """

        now_ms = _now_ms()

        # Normalize bytes/str
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw_text = raw.decode("utf-8")
            except Exception:
                return HandlerResult(
                    ack=self._error_builder.build_error(
                        code=ErrorCode.INVALID_MESSAGE,
                        message="Invalid UTF-8 payload",
                        now_ms=now_ms,
                        request_msg_id=None,
                        room_id=None,
                    )
                )
        else:
            raw_text = str(raw)

        if len(raw_text.encode("utf-8")) > self._config.max_message_bytes:
            return HandlerResult(
                ack=self._error_builder.build_error(
                    code=ErrorCode.INVALID_MESSAGE,
                    message="Message too large",
                    now_ms=now_ms,
                    request_msg_id=None,
                    room_id=None,
                    details={"max_bytes": self._config.max_message_bytes},
                )
            )

        # JSON parse
        try:
            msg = json.loads(raw_text)
        except Exception:
            return HandlerResult(
                ack=self._error_builder.build_error(
                    code=ErrorCode.INVALID_MESSAGE,
                    message="Invalid JSON",
                    now_ms=now_ms,
                    request_msg_id=None,
                    room_id=None,
                )
            )

        if not isinstance(msg, dict):
            return HandlerResult(
                ack=self._error_builder.build_error(
                    code=ErrorCode.INVALID_MESSAGE,
                    message="Message must be a JSON object",
                    now_ms=now_ms,
                    request_msg_id=None,
                    room_id=None,
                )
            )

        # Base fields
        msg_id = msg.get("msg_id")
        msg_type = msg.get("type")
        room_id = msg.get("room_id")
        ts_ms = _normalize_client_timestamp_ms(msg.get("timestamp"))

        if not isinstance(msg_id, str) or not msg_id:
            return HandlerResult(
                ack=self._error_builder.build_error(
                    code=ErrorCode.INVALID_MESSAGE,
                    message="Missing/invalid msg_id",
                    now_ms=now_ms,
                    request_msg_id=None,
                    room_id=room_id if isinstance(room_id, str) else None,
                )
            )

        # Dedup first: replay stored sender response only (no broadcasts).
        cached = self._dedup.get(msg_id)
        if cached is not None:
            return HandlerResult(ack=cached, broadcasts=[])

        if not isinstance(msg_type, str) or msg_type.lower() not in self.CLIENT_TYPES:
            err = self._error_builder.build_error(
                code=ErrorCode.INVALID_MESSAGE,
                message="Unknown/invalid message type",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
                details={"type": msg_type},
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)

        if ts_ms is None:
            err = self._error_builder.build_error(
                code=ErrorCode.INVALID_MESSAGE,
                message="Missing/invalid timestamp",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)

        if abs(now_ms - ts_ms) > self._config.timestamp_tolerance_sec * 1000:
            err = self._error_builder.build_error(
                code=ErrorCode.INVALID_MESSAGE,
                message="Timestamp outside tolerance",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
                details={
                    "tolerance_sec": self._config.timestamp_tolerance_sec,
                    "now_ms": now_ms,
                    "timestamp_ms": ts_ms,
                },
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)

        # Optional schema validation hook (Worker-A provides real validator).
        if self._schema_validator is not None:
            try:
                self._schema_validator(msg)
            except Exception as e:
                err = self._error_builder.build_error(
                    code=ErrorCode.INVALID_MESSAGE,
                    message="Schema validation failed",
                    now_ms=now_ms,
                    request_msg_id=msg_id,
                    room_id=room_id if isinstance(room_id, str) else None,
                    details={"error": str(e)},
                )
                self._dedup.set(msg_id, err)
                return HandlerResult(ack=err)

        # Rate limiting (per connection_id). Duplicates are already handled above.
        bucket = self._buckets.get(connection_id)
        if bucket is None:
            bucket = _TokenBucket(self._config.rate_capacity, self._config.rate_refill_per_sec)
            self._buckets[connection_id] = bucket
        if not bucket.consume(1.0):
            err = self._error_builder.build_error(
                code=ErrorCode.RATE_LIMIT,
                message="Rate limit exceeded",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)

        # Route
        handler = self._handlers.get(msg_type.lower())
        if handler is None:
            err = self._error_builder.build_error(
                code=ErrorCode.INVALID_MESSAGE,
                message="No handler for message type",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
                details={"type": msg_type},
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)

        ctx = HandlerContext(
            connection_id=connection_id,
            connection_manager=self._connection_manager,
            room_manager=self._room_manager,
            state_manager=self._state_manager,
            error_builder=self._error_builder,
            now_ms=now_ms,
            config=self._config,
        )

        try:
            result = await handler.handle(ctx, msg)
        except RoomEventRateLimitError:
            err = self._error_builder.build_error(
                code=ErrorCode.RATE_LIMIT,
                message="Room event rate limit exceeded",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
                details={"scope": "room_events"},
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)
        except Exception as e:
            err = self._error_builder.build_error(
                code=ErrorCode.INTERNAL_ERROR,
                message="Internal error",
                now_ms=now_ms,
                request_msg_id=msg_id,
                room_id=room_id if isinstance(room_id, str) else None,
                details={"error": str(e), "trace_id": str(uuid.uuid4())},
            )
            self._dedup.set(msg_id, err)
            return HandlerResult(ack=err)

        # Store sender reply for dedup (replay only ack/error; no broadcasts).
        if isinstance(result, HandlerResult) and isinstance(result.ack, dict):
            self._dedup.set(msg_id, result.ack)
        return result

