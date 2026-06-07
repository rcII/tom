"""Fold an event stream into the relationship graph.

The graph is one of the two views of the shared-context model (the other is
agent status); both are folded from the same durable log. The property that
matters here is determinism: replaying the same events — in *any* enumeration
order — must yield exactly the same nodes and edges. The file-mirror hands us
events as an unordered directory of files, so we impose a total order ourselves
(by timestamp, then by a stable identity) rather than trusting the order the
files happen to arrive in. Killing the projector and rebuilding from the same
log is therefore the only path to a projection, and it is reproducible.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from tom.projection.events import Dispatch, Envelope
from tom.projection.kinds import kind_from_subject
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind


@dataclass(frozen=True, slots=True)
class GraphProjection:
    """The nodes and edges derived from a stream of events, in a stable order."""

    nodes: tuple[Node, ...]
    edges: tuple[InteractionEdge, ...]


def _parse_ts(ts: str, *, origin: str) -> datetime:
    """Parse an ISO-8601 timestamp, failing loud on anything we can't order.

    A naive timestamp is rejected: ordering a mix of aware and naive datetimes
    raises at runtime, and a silently-dropped offset would make the projection
    order depend on the local zone. Both are correctness bugs, not edge cases.
    """
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp {ts!r} on {origin}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {ts!r} on {origin} has no timezone offset")
    return parsed


def project_graph(
    events: Iterable[Envelope | Dispatch],
    *,
    since: str | None = None,
) -> GraphProjection:
    """Project ``events`` into the relationship graph.

    ``since`` is an inclusive lower bound on edge timestamps (an ISO-8601
    instant): edges older than it are dropped, which is how the bounded history
    window is applied. It is passed explicitly rather than read from the clock
    so the projection stays a pure function of its inputs.

    Events are deduplicated by natural identity (message id for envelopes,
    sub-agent id for dispatches), so an at-least-once replay that re-delivers a
    message produces no duplicate edge.
    """
    since_dt = _parse_ts(since, origin="window cutoff") if since is not None else None

    envelopes: dict[str, Envelope] = {}
    dispatches: dict[str, Dispatch] = {}
    for event in events:
        if isinstance(event, Envelope):
            envelopes.setdefault(event.message_id, event)
        else:
            dispatches.setdefault(event.subagent_id, event)

    nodes: dict[str, Node] = {}

    def ensure_node(node_id: str, kind: NodeKind) -> None:
        # A session identity dominates a sub-agent one, regardless of which
        # event introduced the id first — keeping node kinds order-independent.
        existing = nodes.get(node_id)
        if existing is None:
            nodes[node_id] = Node(id=node_id, kind=kind)
        elif existing.kind is NodeKind.SUBAGENT and kind is NodeKind.SESSION:
            nodes[node_id] = Node(id=node_id, kind=NodeKind.SESSION)

    # Each row carries its sort key alongside the edge so the final order is a
    # total order (timestamp, then identity), independent of input order.
    rows: list[tuple[datetime, str, str, str, InteractionEdge]] = []

    for env in envelopes.values():
        ts = _parse_ts(env.ts, origin=f"envelope {env.message_id}")
        if since_dt is not None and ts < since_dt:
            continue
        ensure_node(env.src, NodeKind.SESSION)
        ensure_node(env.dst, NodeKind.SESSION)
        edge = InteractionEdge(
            src=env.src,
            dst=env.dst,
            kind=kind_from_subject(env.subject),
            ts=env.ts,
            ref=env.message_id,
        )
        rows.append((ts, edge.src, edge.dst, env.message_id, edge))

    for disp in dispatches.values():
        ts = _parse_ts(disp.ts, origin=f"dispatch {disp.subagent_id}")
        if since_dt is not None and ts < since_dt:
            continue
        ensure_node(disp.requesting_session, NodeKind.SESSION)
        ensure_node(disp.subagent_id, NodeKind.SUBAGENT)
        ref = disp.ref if disp.ref is not None else disp.subagent_id
        edge = InteractionEdge(
            src=disp.requesting_session,
            dst=disp.subagent_id,
            kind=EdgeKind.HANDS_OFF,
            ts=disp.ts,
            ref=ref,
        )
        rows.append((ts, edge.src, edge.dst, ref, edge))

    ordered_edges = tuple(row[4] for row in sorted(rows, key=lambda row: row[:4]))
    ordered_nodes = tuple(sorted(nodes.values(), key=lambda node: node.id))
    return GraphProjection(nodes=ordered_nodes, edges=ordered_edges)
