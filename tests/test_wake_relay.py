"""Deciding who to wake — only idle sessions with pending work, debounced."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tom.wake.relay import SessionState, WakeDecision, decide_wakes

NOW = "2026-06-08T02:00:00-05:00"
DEBOUNCE = timedelta(minutes=2)


def _state(
    session: str,
    *,
    idle: bool = True,
    pending: int = 1,
    last_wake_ts: str | None = None,
) -> SessionState:
    return SessionState(
        session=session,
        pane_id=f"{session}:0",
        idle=idle,
        pending=pending,
        last_wake_ts=last_wake_ts,
    )


def test_idle_session_with_pending_is_woken() -> None:
    (decision,) = decide_wakes([_state("catalyst")], now=NOW, debounce=DEBOUNCE)
    assert decision == WakeDecision(session="catalyst", pane_id="catalyst:0")


def test_busy_session_is_never_woken() -> None:
    # Waking a session mid-turn would interrupt real work.
    assert decide_wakes([_state("catalyst", idle=False)], now=NOW, debounce=DEBOUNCE) == ()


def test_idle_session_with_no_pending_is_left_alone() -> None:
    assert decide_wakes([_state("catalyst", pending=0)], now=NOW, debounce=DEBOUNCE) == ()


def test_recently_woken_session_is_debounced() -> None:
    # Woken 1 minute ago, debounce is 2 minutes → not yet.
    recent = _state("catalyst", last_wake_ts="2026-06-08T01:59:00-05:00")
    assert decide_wakes([recent], now=NOW, debounce=DEBOUNCE) == ()


def test_session_past_the_debounce_window_is_woken_again() -> None:
    # Woken 3 minutes ago, debounce is 2 minutes → wake again.
    stale = _state("catalyst", last_wake_ts="2026-06-08T01:57:00-05:00")
    assert len(decide_wakes([stale], now=NOW, debounce=DEBOUNCE)) == 1


def test_debounce_boundary_is_exclusive() -> None:
    # Exactly debounce ago is still within the window (not yet re-woken).
    at_edge = _state("catalyst", last_wake_ts="2026-06-08T01:58:00-05:00")
    assert decide_wakes([at_edge], now=NOW, debounce=DEBOUNCE) == ()


def test_multiple_sessions_are_decided_independently_and_ordered() -> None:
    states = [
        _state("viz"),  # idle + pending → wake
        _state("catalyst", idle=False),  # busy → skip
        _state("oa", pending=0),  # nothing pending → skip
        _state("tpm"),  # idle + pending → wake
    ]
    decisions = decide_wakes(states, now=NOW, debounce=DEBOUNCE)
    assert tuple(d.session for d in decisions) == ("tpm", "viz")


def test_empty_input_wakes_nobody() -> None:
    assert decide_wakes([], now=NOW, debounce=DEBOUNCE) == ()


def test_naive_now_fails_loud() -> None:
    with pytest.raises(ValueError, match="no timezone offset"):
        decide_wakes([_state("catalyst")], now="2026-06-08T02:00:00", debounce=DEBOUNCE)
