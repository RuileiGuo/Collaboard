from __future__ import annotations

import time
import uuid

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from backend.main import create_app


def _message(message_type: str, user_id: str, room_id: str, payload: dict, *, msg_id: str | None = None) -> dict:
    return {
        "msg_id": msg_id or str(uuid.uuid4()),
        "type": message_type,
        "timestamp": int(time.time() * 1000),
        "user_id": user_id,
        "room_id": room_id,
        "sequence_id": None,
        "payload": payload,
    }


def test_two_users_join_draw_and_leave():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice, client.websocket_connect("/ws/conn-b") as bob:
            alice.send_json(
                _message(
                    "join",
                    "alice",
                    "room-a",
                    {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
                )
            )
            alice_ack = alice.receive_json()
            assert alice_ack["type"] == "ack"

            bob.send_json(
                _message(
                    "join",
                    "bob",
                    "room-a",
                    {"client_version": "1.0.0", "metadata": {"user_name": "Bob", "client_type": "web"}},
                )
            )
            bob_ack = bob.receive_json()
            alice_joined = alice.receive_json()
            assert bob_ack["type"] == "ack"
            assert alice_joined["payload"]["event_type"] == "user_joined"

            alice.send_json(
                _message(
                    "draw",
                    "alice",
                    "room-a",
                    {
                        "stroke_id": "550e8400-e29b-41d4-a716-446655440002",
                        "tool": "pen",
                        "color": "#FF0000",
                        "width": 2,
                        "points": [{"x": 1, "y": 2, "pressure": 1.0}],
                    },
                )
            )
            alice_draw_ack = alice.receive_json()
            alice_draw_broadcast = alice.receive_json()
            bob_draw_broadcast = bob.receive_json()
            assert alice_draw_ack["type"] == "ack"
            assert alice_draw_broadcast["payload"]["event_type"] == "draw"
            assert bob_draw_broadcast["sequence_id"] == alice_draw_broadcast["sequence_id"]

            bob.send_json(
                _message(
                    "leave",
                    "bob",
                    "room-a",
                    {"reason": "manual", "message": "done"},
                )
            )
            bob_leave_ack = bob.receive_json()
            alice_user_left = alice.receive_json()
            assert bob_leave_ack["type"] == "ack"
            assert alice_user_left["payload"]["event_type"] == "user_left"


def test_state_sync_returns_missing_events():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice:
            alice.send_json(
                _message(
                    "join",
                    "alice",
                    "room-sync",
                    {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
                )
            )
            join_ack = alice.receive_json()
            current_sequence = join_ack["payload"]["room_state"]["current_sequence"]

            alice.send_json(_message("clear_propose", "alice", "room-sync", {}))
            prop_ack = alice.receive_json()
            assert prop_ack["type"] == "ack"
            assert prop_ack["payload"].get("cleared") is True
            alice.receive_json()

            alice.send_json(
                _message(
                    "state_sync",
                    "alice",
                    "room-sync",
                    {"last_received_sequence": current_sequence},
                )
            )
            sync_ack = alice.receive_json()
            assert sync_ack["type"] == "ack"
            assert sync_ack["sequence_id"] is None
            assert sync_ack["payload"]["room_state"]["canvas_events"][-1]["payload"]["event_type"] == "clear"


def test_two_users_clear_propose_and_vote():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice, client.websocket_connect("/ws/conn-b") as bob:
            for ws, uid, name in (
                (alice, "alice", "Alice"),
                (bob, "bob", "Bob"),
            ):
                ws.send_json(
                    _message(
                        "join",
                        uid,
                        "room-clear",
                        {"client_version": "1.0.0", "metadata": {"user_name": name, "client_type": "web"}},
                    )
                )
                assert ws.receive_json()["type"] == "ack"
            alice.receive_json()

            alice.send_json(_message("clear_propose", "alice", "room-clear", {"message": "reset"}))
            prop_ack = alice.receive_json()
            alice_prop_br = alice.receive_json()
            bob_prop = bob.receive_json()
            assert prop_ack["type"] == "ack"
            assert prop_ack["payload"]["proposal_id"]
            assert alice_prop_br["payload"]["event_type"] == "clear_propose"
            assert bob_prop["payload"]["event_type"] == "clear_propose"
            pid = prop_ack["payload"]["proposal_id"]

            bob.send_json(
                _message(
                    "clear_vote",
                    "bob",
                    "room-clear",
                    {"proposal_id": pid, "vote": "approve"},
                )
            )
            bob_ack = bob.receive_json()
            alice_clear = alice.receive_json()
            bob_clear = bob.receive_json()
            assert bob_ack["type"] == "ack"
            assert bob_ack["payload"].get("cleared") is True
            assert alice_clear["payload"]["event_type"] == "clear"
            assert bob_clear["payload"]["event_type"] == "clear"


def test_direct_clear_rejected():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice:
            alice.send_json(
                _message(
                    "join",
                    "alice",
                    "room-dc",
                    {"client_version": "1.0.0", "metadata": {"user_name": "Alice", "client_type": "web"}},
                )
            )
            alice.receive_json()
            alice.send_json(_message("clear", "alice", "room-dc", {"clear_type": "full"}))
            err = alice.receive_json()
            assert err["type"] == "error"
            assert err["payload"]["error_code"] == "CLEAR_REQUIRES_CONSENSUS"


def test_annotation_delete_creator_only():
    aid = "550e8400-e29b-41d4-a716-446655440099"
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice, client.websocket_connect("/ws/conn-b") as bob:
            for ws, uid, name in ((alice, "alice", "Alice"), (bob, "bob", "Bob")):
                ws.send_json(
                    _message(
                        "join",
                        uid,
                        "room-ann",
                        {"client_version": "1.0.0", "metadata": {"user_name": name, "client_type": "web"}},
                    )
                )
                assert ws.receive_json()["type"] == "ack"
            alice.receive_json()

            alice.send_json(
                _message(
                    "annotation",
                    "alice",
                    "room-ann",
                    {
                        "annotation_id": aid,
                        "mode": "text",
                        "content": "hello",
                        "x": 10,
                        "y": 20,
                        "font_size": 16,
                        "color": "#112233",
                    },
                )
            )
            assert alice.receive_json()["type"] == "ack"
            ann_br_alice = alice.receive_json()
            ann_br_bob = bob.receive_json()
            assert ann_br_alice["payload"]["event_type"] == "annotation"
            assert ann_br_bob["payload"]["event_type"] == "annotation"

            bob.send_json(_message("annotation_delete", "bob", "room-ann", {"annotation_id": aid}))
            bob_err = bob.receive_json()
            assert bob_err["type"] == "error"
            assert bob_err["payload"]["error_code"] == "UNAUTHORIZED"

            alice.send_json(_message("annotation_delete", "alice", "room-ann", {"annotation_id": aid}))
            assert alice.receive_json()["type"] == "ack"
            rem_alice = alice.receive_json()
            rem_bob = bob.receive_json()
            assert rem_alice["payload"]["event_type"] == "annotation_removed"
            assert rem_bob["payload"]["event_type"] == "annotation_removed"
            assert rem_bob["payload"]["annotation_id"] == aid

            alice.send_json(_message("annotation_delete", "alice", "room-ann", {"annotation_id": aid}))
            not_found = alice.receive_json()
            assert not_found["type"] == "error"
            assert not_found["payload"]["error_code"] == "ANNOTATION_NOT_FOUND"


def test_draw_undo_author_only():
    sid = "550e8400-e29b-41d4-a716-4466554400b1"
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice, client.websocket_connect("/ws/conn-b") as bob:
            for ws, uid, name in ((alice, "alice", "Alice"), (bob, "bob", "Bob")):
                ws.send_json(
                    _message(
                        "join",
                        uid,
                        "room-undo-draw",
                        {"client_version": "1.0.0", "metadata": {"user_name": name, "client_type": "web"}},
                    )
                )
                assert ws.receive_json()["type"] == "ack"
            alice.receive_json()

            alice.send_json(
                _message(
                    "draw",
                    "alice",
                    "room-undo-draw",
                    {
                        "stroke_id": sid,
                        "tool": "pen",
                        "color": "#FF0000",
                        "width": 2,
                        "points": [{"x": 1, "y": 2, "pressure": 1.0}],
                    },
                )
            )
            assert alice.receive_json()["type"] == "ack"
            alice.receive_json()
            bob.receive_json()

            bob.send_json(_message("draw_undo", "bob", "room-undo-draw", {"stroke_id": sid}))
            bob_err = bob.receive_json()
            assert bob_err["type"] == "error"
            assert bob_err["payload"]["error_code"] == "UNAUTHORIZED"

            alice.send_json(_message("draw_undo", "alice", "room-undo-draw", {"stroke_id": sid}))
            assert alice.receive_json()["type"] == "ack"
            u_alice = alice.receive_json()
            u_bob = bob.receive_json()
            assert u_alice["payload"]["event_type"] == "stroke_undone"
            assert u_bob["payload"]["event_type"] == "stroke_undone"

            alice.send_json(_message("draw_undo", "alice", "room-undo-draw", {"stroke_id": sid}))
            nf = alice.receive_json()
            assert nf["type"] == "error"
            assert nf["payload"]["error_code"] == "STROKE_NOT_FOUND"


def test_draw_undo_then_redo():
    sid = "550e8400-e29b-41d4-a716-4466554400d3"
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice, client.websocket_connect("/ws/conn-b") as bob:
            for ws, uid, name in ((alice, "alice", "Alice"), (bob, "bob", "Bob")):
                ws.send_json(
                    _message(
                        "join",
                        uid,
                        "room-redo",
                        {"client_version": "1.0.0", "metadata": {"user_name": name, "client_type": "web"}},
                    )
                )
                assert ws.receive_json()["type"] == "ack"
            alice.receive_json()

            alice.send_json(
                _message(
                    "draw",
                    "alice",
                    "room-redo",
                    {
                        "stroke_id": sid,
                        "tool": "pen",
                        "color": "#00FF00",
                        "width": 3,
                        "points": [{"x": 1, "y": 1, "pressure": 1.0}, {"x": 5, "y": 5, "pressure": 1.0}],
                    },
                )
            )
            assert alice.receive_json()["type"] == "ack"
            alice.receive_json()
            bob.receive_json()

            alice.send_json(_message("draw_undo", "alice", "room-redo", {"stroke_id": sid}))
            assert alice.receive_json()["type"] == "ack"
            alice.receive_json()
            bob.receive_json()

            alice.send_json(_message("draw_redo", "alice", "room-redo", {"stroke_id": sid}))
            assert alice.receive_json()["type"] == "ack"
            r_alice = alice.receive_json()
            r_bob = bob.receive_json()
            assert r_alice["payload"]["event_type"] == "draw"
            assert r_bob["payload"]["event_type"] == "draw"
            assert r_bob["payload"]["stroke_id"] == sid

            alice.send_json(_message("draw_redo", "alice", "room-redo", {"stroke_id": sid}))
            dup = alice.receive_json()
            assert dup["type"] == "error"
            assert dup["payload"]["error_code"] == "STROKE_NOT_FOUND"


def test_annotation_restore_after_delete():
    aid = "550e8400-e29b-41d4-a716-4466554400c2"
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/conn-a") as alice, client.websocket_connect("/ws/conn-b") as bob:
            for ws, uid, name in ((alice, "alice", "Alice"), (bob, "bob", "Bob")):
                ws.send_json(
                    _message(
                        "join",
                        uid,
                        "room-restore",
                        {"client_version": "1.0.0", "metadata": {"user_name": name, "client_type": "web"}},
                    )
                )
                assert ws.receive_json()["type"] == "ack"
            alice.receive_json()

            alice.send_json(
                _message(
                    "annotation",
                    "alice",
                    "room-restore",
                    {
                        "annotation_id": aid,
                        "mode": "formula",
                        "content": "E=mc^2",
                        "x": 5,
                        "y": 6,
                        "font_size": 18,
                        "color": "#112233",
                    },
                )
            )
            assert alice.receive_json()["type"] == "ack"
            alice.receive_json()
            bob.receive_json()

            alice.send_json(_message("annotation_delete", "alice", "room-restore", {"annotation_id": aid}))
            assert alice.receive_json()["type"] == "ack"
            alice.receive_json()
            bob.receive_json()

            bob.send_json(_message("annotation_restore", "bob", "room-restore", {"annotation_id": aid}))
            bob_err = bob.receive_json()
            assert bob_err["type"] == "error"
            assert bob_err["payload"]["error_code"] == "ANNOTATION_NOT_FOUND"

            alice.send_json(_message("annotation_restore", "alice", "room-restore", {"annotation_id": aid}))
            assert alice.receive_json()["type"] == "ack"
            rest_a = alice.receive_json()
            rest_b = bob.receive_json()
            assert rest_a["payload"]["event_type"] == "annotation"
            assert rest_b["payload"]["event_type"] == "annotation"
            assert rest_b["payload"]["content"] == "E=mc^2"
            assert rest_b["payload"]["annotation_id"] == aid
