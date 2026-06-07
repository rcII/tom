"""The status projection folds signals into per-agent status, deterministically.

Covers the status half of the shared-context model: active / blocked / measured
idle from a session's own signals, inferred idle when a session goes quiet, and
an identical rebuild on replay.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tom.projection.events import SignalKind, StatusSignal
from tom.projection.status import project_status
from tom.schemas.status import AgentStatus, IdleBasis, State

TTL = timedelta(minutes=10)
NOW = "2026-06-07T01:30:00-05:00"


def _signal(
    session: str,
    ts: str,
    kind: SignalKind,
    task: str | None = None,
    pr: str | None = None,
    stage: str | None = None,
) -> StatusSignal:
    return StatusSignal(session=session, ts=ts, kind=kind, task=task, pr=pr, stage=stage)


def test_recent_started_session_is_active() -> None:
    signals = [
        _signal("tom", "2026-06-07T01:25:00-05:00", SignalKind.STARTED, task="graph projection"),
        _signal("tom", "2026-06-07T01:29:00-05:00", SignalKind.HEARTBEAT),
    ]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status == AgentStatus(
        session="tom",
        state=State.ACTIVE,
        current_task="graph projection",
        since_ts="2026-06-07T01:25:00-05:00",
        last_heartbeat_ts="2026-06-07T01:29:00-05:00",
        idle_basis=None,
    )


def test_blocked_session_carries_blocked_state() -> None:
    signals = [
        _signal("catalyst", "2026-06-07T01:20:00-05:00", SignalKind.STARTED, task="ci fix"),
        _signal("catalyst", "2026-06-07T01:28:00-05:00", SignalKind.BLOCKED),
    ]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status.state == State.BLOCKED
    assert status.since_ts == "2026-06-07T01:28:00-05:00"
    assert status.current_task == "ci fix"
    assert status.idle_basis is None


def test_unblocked_returns_to_active() -> None:
    signals = [
        _signal("catalyst", "2026-06-07T01:20:00-05:00", SignalKind.BLOCKED),
        _signal("catalyst", "2026-06-07T01:27:00-05:00", SignalKind.UNBLOCKED),
    ]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status.state == State.ACTIVE
    assert status.since_ts == "2026-06-07T01:27:00-05:00"


def test_declared_idle_is_measured() -> None:
    signals = [_signal("oa", "2026-06-07T01:29:00-05:00", SignalKind.IDLE)]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status.state == State.IDLE
    assert status.idle_basis == IdleBasis.MEASURED


def test_quiet_session_is_inferred_idle_never_measured() -> None:
    # A session that started a long compute and stopped heartbeating. We cannot
    # prove it is parked, so it is inferred idle — not the confident measured idle.
    signals = [
        _signal("oa", "2026-06-07T01:00:00-05:00", SignalKind.STARTED, task="long backtest"),
        _signal("oa", "2026-06-07T01:05:00-05:00", SignalKind.HEARTBEAT),
    ]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status.state == State.IDLE
    assert status.idle_basis == IdleBasis.INFERRED_NO_HEARTBEAT
    # The last known task is preserved — it was working on this when it went quiet.
    assert status.current_task == "long backtest"
    assert status.since_ts == "2026-06-07T01:05:00-05:00"


def test_idle_window_boundary_is_exclusive_at_ttl() -> None:
    # Exactly TTL old is not yet stale; one second past it is.
    just_inside = [_signal("tom", "2026-06-07T01:20:00-05:00", SignalKind.HEARTBEAT)]
    just_outside = [_signal("tom", "2026-06-07T01:19:59-05:00", SignalKind.HEARTBEAT)]
    (inside,) = project_status(just_inside, now=NOW, idle_ttl=TTL)
    (outside,) = project_status(just_outside, now=NOW, idle_ttl=TTL)
    assert inside.state == State.ACTIVE
    assert outside.state == State.IDLE
    assert outside.idle_basis == IdleBasis.INFERRED_NO_HEARTBEAT


def test_heartbeat_only_session_is_active() -> None:
    signals = [_signal("viz", "2026-06-07T01:29:00-05:00", SignalKind.HEARTBEAT)]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status.state == State.ACTIVE
    assert status.current_task is None


def test_pr_and_stage_carry_forward() -> None:
    signals = [
        _signal(
            "tom", "2026-06-07T01:25:00-05:00", SignalKind.STARTED,
            task="t", pr="#1", stage="s",
        ),
        _signal("tom", "2026-06-07T01:29:00-05:00", SignalKind.HEARTBEAT),
    ]
    (status,) = project_status(signals, now=NOW, idle_ttl=TTL)
    assert status.current_pr == "#1"
    assert status.current_stage == "s"


def test_rebuild_is_order_independent() -> None:
    signals = [
        _signal("tom", "2026-06-07T01:25:00-05:00", SignalKind.STARTED, task="a"),
        _signal("catalyst", "2026-06-07T01:28:00-05:00", SignalKind.BLOCKED),
        _signal("tom", "2026-06-07T01:29:00-05:00", SignalKind.HEARTBEAT),
        _signal("oa", "2026-06-07T01:00:00-05:00", SignalKind.STARTED, task="b"),
    ]
    forward = project_status(signals, now=NOW, idle_ttl=TTL)
    reversed_proj = project_status(list(reversed(signals)), now=NOW, idle_ttl=TTL)
    assert forward == reversed_proj
    assert project_status(signals, now=NOW, idle_ttl=TTL) == forward
    # Three sessions, sorted by name.
    assert tuple(status.session for status in forward) == ("catalyst", "oa", "tom")


def test_empty_stream_is_no_statuses() -> None:
    assert project_status([], now=NOW, idle_ttl=TTL) == ()


def test_naive_now_fails_loud() -> None:
    signals = [_signal("tom", "2026-06-07T01:29:00-05:00", SignalKind.HEARTBEAT)]
    with pytest.raises(ValueError, match="no timezone offset"):
        project_status(signals, now="2026-06-07T01:30:00", idle_ttl=TTL)


def test_naive_signal_ts_fails_loud() -> None:
    signals = [_signal("tom", "2026-06-07T01:29:00", SignalKind.HEARTBEAT)]
    with pytest.raises(ValueError, match="no timezone offset"):
        project_status(signals, now=NOW, idle_ttl=TTL)
