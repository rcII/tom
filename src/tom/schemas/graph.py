"""The relationship graph — the live edge set derived from the same event log.

A node is a session or a dispatched sub-agent (and, as the work needs it, a
task, PR, or artifact). An edge is one interaction; its kind is read from the
validated subject of the event, never inferred from free-text body content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EdgeKind(str, Enum):
    MESSAGE = "message"
    REVIEW_OF = "review-of"
    DEPENDS_ON = "depends-on"
    BLOCKS = "blocks"
    HANDS_OFF = "hands-off"


class NodeKind(str, Enum):
    SESSION = "session"
    SUBAGENT = "subagent"


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: NodeKind
    project: str | None = None


@dataclass(frozen=True, slots=True)
class InteractionEdge:
    src: str
    dst: str
    kind: EdgeKind
    ts: str
    ref: str | None = None
