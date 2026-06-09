"""The status-widget data contract — the shape viz subscribes to (R3).

The console's graph-node status widget renders the projected model: nodes are
sessions (and, as they earn it, sub-agents / tasks / PRs), edges are the
interactions between them, and a handful of derived answers let the widget
highlight the same things an agent would ask the model (who's idle, who blocks
whom, the critical path).

tom serves this; viz subscribes and renders. The transport carries two messages:

- a :class:`StatusSnapshot` — the whole current state, sent on connect and on a
  resync, carrying a monotone ``seq``;
- a :class:`DeltaBatch` — the minimal node/edge changes since the previous
  snapshot, carrying ``from_seq`` → ``to_seq`` so viz can apply it in order and
  detect a gap (``from_seq`` ahead of what it holds → ask for a fresh snapshot).

The widget is render-only and subscribe-only (RFC-001 §5.5): it reflects the
model and never writes it. These types reuse the projection's own enums
(:class:`~tom.schemas.status.State`, :class:`~tom.schemas.graph.EdgeKind`, …)
rather than restating them, so the widget can never drift from the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tom.schemas.graph import EdgeKind, NodeKind
from tom.schemas.status import IdleBasis, State


@dataclass(frozen=True, slots=True)
class WidgetNode:
    """One node in the widget: a session, sub-agent, task, or PR.

    The status fields (``status`` … ``current_stage``) are populated for a node
    that has an agent status; a graph-only node (a sub-agent with no status of
    its own) carries ``status=None`` so the widget shows it without inventing a
    state.
    """

    id: str
    kind: NodeKind
    status: State | None = None
    idle_basis: IdleBasis | None = None
    current_task: str | None = None
    current_pr: str | None = None
    current_stage: str | None = None


@dataclass(frozen=True, slots=True)
class WidgetEdge:
    """One edge in the widget. ``kind`` is colored by the renderer."""

    src: str
    dst: str
    kind: EdgeKind
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedAnswers:
    """The query-verb answers, precomputed so the widget highlights what an agent
    would ask the model. ``blocks`` is ``(blocker, blocked)`` pairs."""

    idle: tuple[str, ...] = ()
    blocks: tuple[tuple[str, str], ...] = ()
    critical_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """The whole current state, at sequence ``seq``.

    ``seq`` is monotone: viz holds the last seq it applied, and a snapshot
    re-bases it. ``generated_ts`` is the producer's stamp at projection time.
    """

    seq: int
    generated_ts: str
    nodes: tuple[WidgetNode, ...] = ()
    edges: tuple[WidgetEdge, ...] = ()
    derived: DerivedAnswers = field(default_factory=DerivedAnswers)


class DeltaOp(StrEnum):
    """The four minimal mutations a delta carries."""

    NODE_UPSERT = "node-upsert"
    NODE_REMOVE = "node-remove"
    EDGE_ADD = "edge-add"
    EDGE_REMOVE = "edge-remove"


@dataclass(frozen=True, slots=True)
class StatusDelta:
    """One mutation. Exactly one of ``node`` / ``node_id`` / ``edge`` is set, per
    the ``op``: an upsert carries the new ``node``; a node-remove carries the
    ``node_id``; an edge add/remove carries the ``edge``."""

    op: DeltaOp
    node: WidgetNode | None = None
    node_id: str | None = None
    edge: WidgetEdge | None = None


@dataclass(frozen=True, slots=True)
class DeltaBatch:
    """The minimal changes that turn the ``from_seq`` snapshot into ``to_seq``.

    Applied atomically and in order. If ``from_seq`` is ahead of the seq viz
    holds, it missed a batch and asks for a fresh snapshot; an empty ``deltas``
    with ``to_seq > from_seq`` is a valid no-op advance (nothing changed).
    """

    from_seq: int
    to_seq: int
    ts: str
    deltas: tuple[StatusDelta, ...] = ()
