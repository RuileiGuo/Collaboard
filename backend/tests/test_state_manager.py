from __future__ import annotations

from backend.core.models import RoomState, UserState
from backend.core.state_manager import StateManager


def test_valid_user_transition_flow():
    manager = StateManager()
    manager.on_connected("alice", "conn-1", now=0)
    assert manager.get_user_state("alice") == UserState.CONNECTED
    manager.on_join("alice", "room-a", now=1)
    assert manager.get_user_state("alice") == UserState.JOINED
    manager.on_activity("alice", now=2)
    assert manager.get_user_state("alice") == UserState.ACTIVE
    manager.on_leave("alice", now=3)
    assert manager.get_user_state("alice") == UserState.LEFT


def test_connected_without_join_times_out():
    manager = StateManager()
    manager.on_connected("alice", "conn-1", now=0)
    events = manager.apply_timeouts(now=31)
    assert any(event.reason == "join_timeout" for event in events)
    assert manager.get_user_state("alice") == UserState.DISCONNECTED


def test_idle_user_times_out_to_disconnected():
    from backend.core.state_manager import ACTIVE_IDLE_SECONDS, IDLE_TIMEOUT_SECONDS

    manager = StateManager()
    manager.on_connected("alice", "conn-1", now=0)
    manager.on_join("alice", "room-a", now=1)
    manager.on_activity("alice", now=2)
    idle_at = 2 + ACTIVE_IDLE_SECONDS + 1
    manager.apply_timeouts(now=idle_at)
    assert manager.get_user_state("alice") == UserState.IDLE
    disconnected_at = idle_at + IDLE_TIMEOUT_SECONDS + 1
    manager.apply_timeouts(now=disconnected_at)
    assert manager.get_user_state("alice") == UserState.DISCONNECTED


def test_online_user_keeps_session_while_connected():
    manager = StateManager()
    manager.on_connected("alice", "conn-1", now=0)
    manager.on_join("alice", "room-a", now=1)
    manager.on_activity("alice", now=2)
    manager.apply_timeouts(now=100_000, online_user_ids={"alice"})
    assert manager.get_user_state("alice") == UserState.ACTIVE


def test_restore_room_session_after_disconnect():
    manager = StateManager()
    manager.on_connected("alice", "conn-1", now=0)
    manager.on_join("alice", "room-a", now=1)
    manager.on_activity("alice", now=2)
    manager.on_disconnect("alice", now=3)
    assert manager.get_user_state("alice") == UserState.DISCONNECTED
    manager.restore_room_session("alice", "room-a", connection_id="conn-1", now=4)
    assert manager.get_user_state("alice") == UserState.ACTIVE
    assert manager.validate_user_action("alice", "draw") is True


def test_room_transition_validation():
    manager = StateManager()
    assert manager.validate_room_transition(RoomState.PENDING_INIT, "join") is True
    assert manager.validate_room_transition(RoomState.ACTIVE, "leave_last") is True
    assert manager.validate_room_transition(RoomState.DESTROYED, "join") is False
