"""JSON Schema definitions and validators for CollabBoard messages."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from jsonschema import Draft7Validator

from backend import config
from backend.core.models import MessageType
from backend.utils.exceptions import ProtocolValidationError


UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

CLIENT_MESSAGE_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "msg_id": {"type": "string", "pattern": UUID_PATTERN},
        "type": {
            "type": "string",
            "enum": [
                MessageType.JOIN.value,
                MessageType.LEAVE.value,
                MessageType.DRAW.value,
                MessageType.ANNOTATION.value,
                MessageType.ANNOTATION_DELETE.value,
                MessageType.ANNOTATION_RESTORE.value,
                MessageType.DRAW_UNDO.value,
                MessageType.DRAW_REDO.value,
                MessageType.CLEAR.value,
                MessageType.CLEAR_PROPOSE.value,
                MessageType.CLEAR_VOTE.value,
                MessageType.STATE_SYNC.value,
            ],
        },
        "timestamp": {"type": "number", "minimum": 0},
        "user_id": {"type": "string", "minLength": 1, "maxLength": 100},
        "room_id": {"type": "string", "minLength": 1, "maxLength": 100},
        "sequence_id": {"type": ["null"]},
        "payload": {"type": "object"},
    },
    "required": ["msg_id", "type", "timestamp", "user_id", "room_id", "payload"],
    "additionalProperties": False,
}

JOIN_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "client_version": {"type": "string"},
        "metadata": {
            "type": "object",
            "properties": {
                "user_name": {"type": "string", "minLength": 1, "maxLength": 100},
                "client_type": {"type": "string"},
            },
            "additionalProperties": True,
        },
    },
    "required": ["client_version", "metadata"],
    "additionalProperties": False,
}

LEAVE_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "enum": ["manual", "disconnect", "timeout", "error"],
        },
        "message": {"type": "string"},
    },
    "required": ["reason"],
    "additionalProperties": False,
}

DRAW_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "stroke_id": {"type": "string", "pattern": UUID_PATTERN},
        "tool": {
            "type": "string",
            "enum": ["pen", "eraser", "line", "rectangle", "circle"],
        },
        "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
        "width": {"type": "number", "minimum": 0.5, "maximum": 50},
        "points": {
            "type": "array",
            "maxItems": 1000,
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "pressure": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["x", "y", "pressure"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["stroke_id", "tool", "color", "width", "points"],
    "additionalProperties": False,
}

CLEAR_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "clear_type": {"type": "string", "enum": ["full"]},
    },
    "required": ["clear_type"],
    "additionalProperties": False,
}

ANNOTATION_DELETE_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "annotation_id": {"type": "string", "pattern": UUID_PATTERN},
    },
    "required": ["annotation_id"],
    "additionalProperties": False,
}

ANNOTATION_RESTORE_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "annotation_id": {"type": "string", "pattern": UUID_PATTERN},
    },
    "required": ["annotation_id"],
    "additionalProperties": False,
}

DRAW_UNDO_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "stroke_id": {"type": "string", "pattern": UUID_PATTERN},
    },
    "required": ["stroke_id"],
    "additionalProperties": False,
}

DRAW_REDO_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "stroke_id": {"type": "string", "pattern": UUID_PATTERN},
    },
    "required": ["stroke_id"],
    "additionalProperties": False,
}

ANNOTATION_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "annotation_id": {"type": "string", "pattern": UUID_PATTERN},
        "mode": {"type": "string", "enum": ["text", "formula"]},
        "content": {"type": "string", "minLength": 1, "maxLength": config.ANNOTATION_CONTENT_MAX_CHARS},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "font_size": {
            "type": "number",
            "minimum": config.ANNOTATION_FONT_SIZE_MIN,
            "maximum": config.ANNOTATION_FONT_SIZE_MAX,
        },
        "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
    },
    "required": ["annotation_id", "mode", "content", "x", "y", "font_size", "color"],
    "additionalProperties": False,
}

CLEAR_PROPOSE_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "maxLength": 500},
    },
    "additionalProperties": False,
}

CLEAR_VOTE_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposal_id": {"type": "string", "pattern": UUID_PATTERN},
        "vote": {"type": "string", "enum": ["approve", "reject"]},
    },
    "required": ["proposal_id", "vote"],
    "additionalProperties": False,
}

STATE_SYNC_PAYLOAD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "last_received_sequence": {"type": "integer", "minimum": -1},
    },
    "required": ["last_received_sequence"],
    "additionalProperties": False,
}

PAYLOAD_SCHEMAS: Dict[str, Dict[str, Any]] = {
    MessageType.JOIN.value: JOIN_PAYLOAD_SCHEMA,
    MessageType.LEAVE.value: LEAVE_PAYLOAD_SCHEMA,
    MessageType.DRAW.value: DRAW_PAYLOAD_SCHEMA,
    MessageType.ANNOTATION.value: ANNOTATION_PAYLOAD_SCHEMA,
    MessageType.ANNOTATION_DELETE.value: ANNOTATION_DELETE_PAYLOAD_SCHEMA,
    MessageType.ANNOTATION_RESTORE.value: ANNOTATION_RESTORE_PAYLOAD_SCHEMA,
    MessageType.DRAW_UNDO.value: DRAW_UNDO_PAYLOAD_SCHEMA,
    MessageType.DRAW_REDO.value: DRAW_REDO_PAYLOAD_SCHEMA,
    MessageType.CLEAR.value: CLEAR_PAYLOAD_SCHEMA,
    MessageType.CLEAR_PROPOSE.value: CLEAR_PROPOSE_PAYLOAD_SCHEMA,
    MessageType.CLEAR_VOTE.value: CLEAR_VOTE_PAYLOAD_SCHEMA,
    MessageType.STATE_SYNC.value: STATE_SYNC_PAYLOAD_SCHEMA,
}


_ANNOTATION_FORBIDDEN_SUBSTRINGS = (
    "<script",
    "</script",
    "javascript:",
    "onerror=",
    "onload=",
    "<iframe",
    "data:text/html",
)


def assert_annotation_content_safe(content: str) -> None:
    lower = content.lower()
    for frag in _ANNOTATION_FORBIDDEN_SUBSTRINGS:
        if frag in lower:
            raise ProtocolValidationError(
                f"Annotation content contains forbidden fragment: {frag!r}",
                details={"field": "content"},
            )

_BASE_VALIDATOR = Draft7Validator(CLIENT_MESSAGE_SCHEMA)
_PAYLOAD_VALIDATORS = {
    message_type: Draft7Validator(schema)
    for message_type, schema in PAYLOAD_SCHEMAS.items()
}


def _raise_first_error(errors: list[Any]) -> None:
    if errors:
        raise ProtocolValidationError(errors[0].message, details={"path": list(errors[0].path)})


def validate_client_message(message: Mapping[str, Any]) -> None:
    base_errors = sorted(_BASE_VALIDATOR.iter_errors(message), key=lambda err: list(err.path))
    _raise_first_error(base_errors)

    message_type = message["type"]
    payload = message.get("payload", {})
    validator = _PAYLOAD_VALIDATORS.get(message_type)
    if validator is None:
        raise ProtocolValidationError(f"Unsupported message type: {message_type}")

    payload_errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    _raise_first_error(payload_errors)

    if message.get("sequence_id") is not None:
        raise ProtocolValidationError("Client requests must use sequence_id=null")

    if message_type == MessageType.ANNOTATION.value:
        assert_annotation_content_safe(str(payload.get("content", "")))
