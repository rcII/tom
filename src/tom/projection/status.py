"""Fold status signals into the per-agent status projection.

This is the other view of the shared-context model: where the graph answers
"who is talking to whom", the status projection answers "what is each session
doing right now". Both are folded from the same durable log, and the same
discipline applies — the projection is a pure function of its inputs, so
killing the projector and replaying the same signals rebuilds an identical
status set.

The one inference here is idle. A session that goes quiet is *inferred* idle —
we have not heard from it within the idle window, but we cannot prove it is not
mid-computation. That is surfaced honestly: such a session carries
``idle_basis = inferred-no-heartbeat``, never the confident ``measured`` idle
reserved for a session that actually told us it was parking. The reference time
``now`` is passed in rather than read from the clock, so the inference stays
deterministic and replayable.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from tom.projection._time import parse_ts
from tom.projection.events import SignalKind, StatusSignal
from tom.schemas.status import AgentStatus, IdleBasis, State

# The state a signal kind asserts while the session is known to be alive.
# HEARTBEAT asserts no state of its own — it only refreshes liveness.
_DECLARED_STATE: dict[SignalKind, State] = {
    SignalKind.STARTED: State.ACTIVE,
    SignalKind.UNBLOCKED: State.ACTIVE,
    SignalKind.BLOCKED: State.BLOCKED,
    SignalKind.IDLE: State.IDLE,
}


def project_status(
    signals: Iterable[StatusSignal],
    *,
    now: str,
    idle_ttl: timedelta,
) -> tuple[AgentStatus, ...]:
    """Project ``signals`` into one :class:`AgentStatus` per session.

    A session is inferred idle when its most recent signal is older than
    ``idle_ttl`` before ``now``. Otherwise it carries the state of its latest
    state-affecting signal — active, blocked, or a measured idle it declared.
    """
    now_dt = parse_ts(now, origin="now")

    grouped: dict[str, list[StatusSignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.session, []).append(signal)

    statuses = [
        _fold_session(session, session_signals, now_dt=now_dt, idle_ttl=idle_ttl)
        for session, session_signals in grouped.items()
    ]
    return tuple(sorted(statuses, key=lambda status: status.session))


def _fold_session(
    session: str,
    signals: list[StatusSignal],
    *,
    now_dt: datetime,
    idle_ttl: timedelta,
) -> AgentStatus:
    ordered = sorted(
        signals,
        key=lambda signal: (parse_ts(signal.ts, origin=f"signal for {session}"), signal.kind),
    )

    task: str | None = None
    pr: str | None = None
    stage: str | None = None
    declared_state = State.ACTIVE
    declared_since = ordered[0].ts
    last_seen = ordered[0].ts

    for signal in ordered:
        last_seen = signal.ts
        if signal.task is not None:
            task = signal.task
        if signal.pr is not None:
            pr = signal.pr
        if signal.stage is not None:
            stage = signal.stage
        asserted = _DECLARED_STATE.get(signal.kind)
        if asserted is not None and asserted is not declared_state:
            declared_state = asserted
            declared_since = signal.ts

    stale = now_dt - parse_ts(last_seen, origin=f"last signal for {session}") > idle_ttl
    if stale:
        return AgentStatus(
            session=session,
            state=State.IDLE,
            current_task=task,
            since_ts=last_seen,
            last_heartbeat_ts=last_seen,
            current_pr=pr,
            current_stage=stage,
            idle_basis=IdleBasis.INFERRED_NO_HEARTBEAT,
        )

    idle_basis = IdleBasis.MEASURED if declared_state is State.IDLE else None
    return AgentStatus(
        session=session,
        state=declared_state,
        current_task=task,
        since_ts=declared_since,
        last_heartbeat_ts=last_seen,
        current_pr=pr,
        current_stage=stage,
        idle_basis=idle_basis,
    )
