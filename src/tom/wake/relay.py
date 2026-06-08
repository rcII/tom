"""Deciding who to wake.

A channel-delivered event only surfaces at a session's next turn boundary, so an
idle session sits on pending work until something pokes it. This is the decision
half of that poke: given each session's state — is its pane idle, does it have
pending events, when was it last woken — return exactly the sessions that should
be woken now.

Two rules keep it safe: never wake a session whose pane is *busy* (that would
interrupt real work), and never wake the same session twice inside a debounce
window (a delivered-but-not-yet-acked event shouldn't cause a wake storm). The
reference time is passed in, not read from the clock, so the decision is a pure
function of its inputs and is reproducible in a test.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from tom.projection._time import parse_ts


@dataclass(frozen=True, slots=True)
class SessionState:
    """What the relay knows about one session right now."""

    session: str
    #: The configured tmux target (session:window or session:window.pane) — a
    #: string the relay resolves to a specific pane, NOT a %N pane id.
    target: str
    #: True when the pane is sitting idle (at the prompt), not mid-turn.
    idle: bool
    #: Count of delivered-but-unsurfaced events waiting for this session.
    pending: int
    #: When this session was last woken, if ever — for debounce.
    last_wake_ts: str | None = None


@dataclass(frozen=True, slots=True)
class WakeDecision:
    session: str
    target: str


def decide_wakes(
    states: Iterable[SessionState],
    *,
    now: str,
    debounce: timedelta,
) -> tuple[WakeDecision, ...]:
    """Return the sessions to wake now, ordered by session name."""
    now_dt = parse_ts(now, origin="now")
    decisions: list[WakeDecision] = []
    for state in states:
        if not state.idle:
            continue  # busy — waking it would interrupt real work
        if state.pending <= 0:
            continue  # nothing waiting, no reason to wake
        if state.last_wake_ts is not None:
            since_wake = now_dt - parse_ts(
                state.last_wake_ts, origin=f"last wake for {state.session}"
            )
            if since_wake <= debounce:
                continue  # woken recently — don't storm it
        decisions.append(WakeDecision(session=state.session, target=state.target))
    return tuple(sorted(decisions, key=lambda decision: decision.session))
