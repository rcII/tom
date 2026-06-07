"""Agent status — the current node-state in the shared-context model.

Every field is a projection of the durable event log + the dispatch record +
heartbeats. No field is ever sourced from in-memory-only state, so killing the
projector and replaying the same log yields exactly this record again.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    BLOCKED = "blocked"


class IdleBasis(str, Enum):
    MEASURED = "measured"
    INFERRED_NO_HEARTBEAT = "inferred-no-heartbeat"


@dataclass(frozen=True, slots=True)
class AgentStatus:
    session: str
    state: State
    current_task: str | None = None
    since_ts: str | None = None
    last_heartbeat_ts: str | None = None
    current_pr: str | None = None
    current_stage: str | None = None
    #: only meaningful when state is IDLE; an alive-but-quiet session is
    #: surfaced as inferred, never as a confident measured idle.
    idle_basis: IdleBasis | None = None
