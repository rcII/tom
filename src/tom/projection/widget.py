"""Serving the status-widget contract off the projected model.

Two pure functions: build a :class:`StatusSnapshot` from the projected status +
graph, and diff two snapshots into the minimal :class:`DeltaBatch` that turns one
into the other. Both are deterministic — the same inputs yield byte-identical
output — so a snapshot is reproducible and a delta is stable, which is what lets
viz apply deltas in order and trust a resync.

The widget node set is the union of every session that has an agent status and
every node the graph knows (a sub-agent with edges but no status of its own). A
status-bearing node carries its full state; a graph-only node carries
``status=None`` rather than a guessed one.
"""

from __future__ import annotations

from collections.abc import Iterable

from tom.projection.graph import GraphProjection
from tom.queries import critical_path, who_blocks_whom, who_is_idle
from tom.schemas.graph import NodeKind
from tom.schemas.status import AgentStatus
from tom.schemas.widget import (
    DeltaBatch,
    DeltaOp,
    DerivedAnswers,
    StatusDelta,
    StatusSnapshot,
    WidgetEdge,
    WidgetNode,
)


def snapshot_from_projection(
    statuses: Iterable[AgentStatus],
    graph: GraphProjection,
    *,
    seq: int,
    generated_ts: str,
) -> StatusSnapshot:
    """Build the widget snapshot from the projected status + graph.

    ``seq`` and ``generated_ts`` are passed in (not read from a clock or a
    counter) so the function stays pure and the snapshot is reproducible.
    """
    by_session = {status.session: status for status in statuses}
    graph_kind = {node.id: node.kind for node in graph.nodes}
    node_ids = sorted(set(by_session) | set(graph_kind))

    nodes = tuple(
        _widget_node(node_id, by_session.get(node_id), graph_kind.get(node_id))
        for node_id in node_ids
    )
    edges = tuple(
        sorted(
            (WidgetEdge(e.src, e.dst, e.kind, e.ref) for e in graph.edges),
            key=_edge_sort_key,
        )
    )
    # who_is_idle wants the same iterable twice; materialize so it isn't consumed.
    statuses_list = list(by_session.values())
    derived = DerivedAnswers(
        idle=tuple(status.session for status in who_is_idle(statuses_list)),
        blocks=who_blocks_whom(graph),
        critical_path=critical_path(graph),
    )
    return StatusSnapshot(
        seq=seq, generated_ts=generated_ts, nodes=nodes, edges=edges, derived=derived
    )


def delta_between(prev: StatusSnapshot, curr: StatusSnapshot) -> DeltaBatch:
    """The minimal batch that turns ``prev`` into ``curr``.

    Upserts a node whose fields changed (or that is new), removes one that's
    gone, and adds/removes edges by identity. Ops are emitted in a deterministic
    order (nodes before edges, each sorted by id/key) so the batch is stable.
    """
    deltas: list[StatusDelta] = []

    prev_nodes = {node.id: node for node in prev.nodes}
    curr_nodes = {node.id: node for node in curr.nodes}
    for node_id in sorted(curr_nodes):
        if curr_nodes[node_id] != prev_nodes.get(node_id):
            deltas.append(StatusDelta(op=DeltaOp.NODE_UPSERT, node=curr_nodes[node_id]))
    for node_id in sorted(prev_nodes):
        if node_id not in curr_nodes:
            deltas.append(StatusDelta(op=DeltaOp.NODE_REMOVE, node_id=node_id))

    prev_edges = {_edge_key(edge): edge for edge in prev.edges}
    curr_edges = {_edge_key(edge): edge for edge in curr.edges}
    for key in sorted(curr_edges):
        if key not in prev_edges:
            deltas.append(StatusDelta(op=DeltaOp.EDGE_ADD, edge=curr_edges[key]))
    for key in sorted(prev_edges):
        if key not in curr_edges:
            deltas.append(StatusDelta(op=DeltaOp.EDGE_REMOVE, edge=prev_edges[key]))

    return DeltaBatch(
        from_seq=prev.seq, to_seq=curr.seq, ts=curr.generated_ts, deltas=tuple(deltas)
    )


def _widget_node(
    node_id: str, status: AgentStatus | None, kind: NodeKind | None
) -> WidgetNode:
    """One widget node, merging an optional agent status with its graph kind.

    A node with a status defaults to a SESSION kind when the graph hasn't named
    one; a graph-only node carries no status fields.
    """
    resolved_kind = kind if kind is not None else NodeKind.SESSION
    if status is None:
        return WidgetNode(id=node_id, kind=resolved_kind)
    return WidgetNode(
        id=node_id,
        kind=resolved_kind,
        status=status.state,
        idle_basis=status.idle_basis,
        current_task=status.current_task,
        current_pr=status.current_pr,
        current_stage=status.current_stage,
    )


def _edge_sort_key(edge: WidgetEdge) -> tuple[str, str, str, str]:
    return (edge.src, edge.dst, edge.kind.value, edge.ref or "")


def _edge_key(edge: WidgetEdge) -> tuple[str, str, str, str]:
    """Edge identity for diffing: an edge is the same edge iff src/dst/kind/ref
    match, so a changed ``ref`` is a remove + add, never a silent mutation."""
    return (edge.src, edge.dst, edge.kind.value, edge.ref or "")
