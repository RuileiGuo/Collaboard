from __future__ import annotations

import pytest

from backend.core.schemas import validate_client_message
from backend.tests.conftest import build_message
from backend.utils.exceptions import ProtocolValidationError


def test_valid_join_message_passes():
    message = build_message(
        "join",
        "alice",
        "room-a",
        {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
    )
    validate_client_message(message)


def test_invalid_uuid_fails():
    message = build_message(
        "join",
        "alice",
        "room-a",
        {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
        msg_id="not-a-uuid",
    )
    with pytest.raises(ProtocolValidationError):
        validate_client_message(message)


def test_draw_points_limit_fails():
    points = [{"x": float(index), "y": float(index), "pressure": 1.0} for index in range(1001)]
    message = build_message(
        "draw",
        "alice",
        "room-a",
        {
            "stroke_id": "550e8400-e29b-41d4-a716-446655440001",
            "tool": "pen",
            "color": "#FF0000",
            "width": 2,
            "points": points,
        },
    )
    with pytest.raises(ProtocolValidationError):
        validate_client_message(message)


def test_sequence_id_must_be_null_for_client_messages():
    message = build_message("clear", "alice", "room-a", {"clear_type": "full"})
    message["sequence_id"] = 1
    with pytest.raises(ProtocolValidationError):
        validate_client_message(message)


def test_draw_redo_valid():
    message = build_message(
        "draw_redo",
        "alice",
        "room-a",
        {"stroke_id": "550e8400-e29b-41d4-a716-446655440001"},
    )
    validate_client_message(message)


def test_draw_undo_valid():
    message = build_message(
        "draw_undo",
        "alice",
        "room-a",
        {"stroke_id": "550e8400-e29b-41d4-a716-446655440001"},
    )
    validate_client_message(message)


def test_annotation_restore_valid():
    message = build_message(
        "annotation_restore",
        "alice",
        "room-a",
        {"annotation_id": "550e8400-e29b-41d4-a716-446655440001"},
    )
    validate_client_message(message)


def test_annotation_delete_valid():
    message = build_message(
        "annotation_delete",
        "alice",
        "room-a",
        {"annotation_id": "550e8400-e29b-41d4-a716-446655440001"},
    )
    validate_client_message(message)


def test_annotation_rejects_script_in_content():
    message = build_message(
        "annotation",
        "alice",
        "room-a",
        {
            "annotation_id": "550e8400-e29b-41d4-a716-446655440001",
            "mode": "text",
            "content": "hello <script>x</script>",
            "x": 10,
            "y": 20,
            "font_size": 16,
            "color": "#112233",
        },
    )
    with pytest.raises(ProtocolValidationError):
        validate_client_message(message)
