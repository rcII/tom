"""The dependency canvas — the shared-context model as a thing you can read.

The status projection and the relationship graph are the framework's own
system-wide picture: who is doing what, who waits on whom, where the critical
path runs. This renders that picture as plain text — one glance at the whole
mesh. It is a pure projection of the model (a read, never a write), so it can be
printed to a terminal, dropped in a ceremony draft, or handed to a person, and a
later graphical surface is just another renderer over the same model.

Everything here goes through the same query verbs an agent would use, so the
canvas shows exactly what the model would answer — no second computation that
could drift from it.
"""

from __future__ import annotations

from collections.abc import Sequence

from tom import queries
from tom.projection.graph import GraphProjection
from tom.schemas.graph import EdgeKind, InteractionEdge
from tom.schemas.status import AgentStatus, IdleBasis, State

_STATE_MARK: dict[State, str] = {
    State.ACTIVE: "●",
    State.BLOCKED: "⚠",
    State.IDLE: "○",
}

# The order relationship kinds are listed in — most operationally urgent first.
_EDGE_KIND_ORDER: tuple[EdgeKind, ...] = (
    EdgeKind.BLOCKS,
    EdgeKind.DEPENDS_ON,
    EdgeKind.REVIEW_OF,
    EdgeKind.HANDS_OFF,
    EdgeKind.MESSAGE,
)


def render_dependency_canvas(
    statuses: Sequence[AgentStatus],
    graph: GraphProjection,
) -> str:
    """Render the status + relationship graph as a readable dependency canvas."""
    sections = [
        _render_agents(statuses),
        _render_relationships(graph),
        _render_critical_path(queries.critical_path(graph)),
        _render_blocks(queries.who_blocks_whom(graph)),
    ]
    return "\n\n".join(sections)


def _render_agents(statuses: Sequence[AgentStatus]) -> str:
    lines = ["Agents"]
    if not statuses:
        lines.append("  (none)")
    for status in sorted(statuses, key=lambda s: s.session):
        mark = _STATE_MARK[status.state]
        detail = _state_detail(status)
        task = f" — {status.current_task}" if status.current_task else ""
        lines.append(f"  {mark} {status.session:<12} {detail}{task}")
    return "\n".join(lines)


def _state_detail(status: AgentStatus) -> str:
    if status.state is State.IDLE and status.idle_basis is IdleBasis.INFERRED_NO_HEARTBEAT:
        return "idle (inferred — no heartbeat)"
    return status.state.value


def _render_relationships(graph: GraphProjection) -> str:
    lines = ["Relationships"]
    by_kind: dict[EdgeKind, list[InteractionEdge]] = {}
    for edge in graph.edges:
        by_kind.setdefault(edge.kind, []).append(edge)
    if not graph.edges:
        lines.append("  (none)")
    for kind in _EDGE_KIND_ORDER:
        edges = by_kind.get(kind)
        if not edges:
            continue
        lines.append(f"  {kind.value}:")
        for edge in sorted(edges, key=lambda e: (e.src, e.dst, e.ref or "")):
            lines.append(f"    {edge.src} → {edge.dst}")
    return "\n".join(lines)


def _render_critical_path(path: tuple[str, ...]) -> str:
    drawn = " → ".join(path) if path else "(none)"
    return f"Critical path\n  {drawn}"


def _render_blocks(pairs: tuple[tuple[str, str], ...]) -> str:
    lines = ["Blocking"]
    if not pairs:
        lines.append("  (none)")
    for blocker, blocked in pairs:
        lines.append(f"  {blocker} blocks {blocked}")
    return "\n".join(lines)
