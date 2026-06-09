"""The status-widget contract: snapshot from the model + minimal stable deltas."""

from __future__ import annotations

from tom.projection.graph import GraphProjection
from tom.projection.widget import delta_between, snapshot_from_projection
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind
from tom.schemas.status import AgentStatus, IdleBasis, State
from tom.schemas.widget import (
    DeltaOp,
    StatusDelta,
    StatusSnapshot,
    WidgetEdge,
    WidgetNode,
)

_TS = "2026-06-09T05:20:00Z"


def _graph(
    nodes: tuple[Node, ...] = (), edges: tuple[InteractionEdge, ...] = ()
) -> GraphProjection:
    return GraphProjection(nodes=nodes, edges=edges)


def test_snapshot_maps_a_status_to_a_full_node() -> None:
    statuses = [
        AgentStatus(
            session="tom",
            state=State.IDLE,
            idle_basis=IdleBasis.MEASURED,
            current_task="R4 wiring",
            current_pr="#26",
        ),
    ]
    snap = snapshot_from_projection(statuses, _graph(), seq=1, generated_ts=_TS)
    assert snap.nodes == (
        WidgetNode(
            id="tom",
            kind=NodeKind.SESSION,
            status=State.IDLE,
            idle_basis=IdleBasis.MEASURED,
            current_task="R4 wiring",
            current_pr="#26",
        ),
    )


def test_graph_only_node_carries_no_status() -> None:
    graph = _graph(nodes=(Node(id="sub-1", kind=NodeKind.SUBAGENT),))
    snap = snapshot_from_projection([], graph, seq=1, generated_ts=_TS)
    assert snap.nodes == (WidgetNode(id="sub-1", kind=NodeKind.SUBAGENT, status=None),)


def test_snapshot_node_set_is_the_union_of_status_and_graph() -> None:
    statuses = [AgentStatus(session="tom", state=State.ACTIVE)]
    graph = _graph(nodes=(Node(id="sub-1", kind=NodeKind.SUBAGENT),))
    snap = snapshot_from_projection(statuses, graph, seq=1, generated_ts=_TS)
    assert {node.id for node in snap.nodes} == {"tom", "sub-1"}


def test_snapshot_derives_idle_blocks_and_critical_path() -> None:
    statuses = [
        AgentStatus(session="tom", state=State.IDLE, idle_basis=IdleBasis.MEASURED),
        AgentStatus(session="catalyst", state=State.ACTIVE),
    ]
    graph = _graph(
        edges=(
            InteractionEdge(src="catalyst", dst="viz", kind=EdgeKind.BLOCKS, ts=_TS),
            InteractionEdge(src="viz", dst="oa", kind=EdgeKind.DEPENDS_ON, ts=_TS),
        )
    )
    snap = snapshot_from_projection(statuses, graph, seq=1, generated_ts=_TS)
    assert snap.derived.idle == ("tom",)
    assert snap.derived.blocks == (("catalyst", "viz"),)
    assert "viz" in snap.derived.critical_path


def test_snapshot_edges_are_sorted_deterministically() -> None:
    graph = _graph(
        edges=(
            InteractionEdge(src="viz", dst="oa", kind=EdgeKind.MESSAGE, ts=_TS),
            InteractionEdge(src="catalyst", dst="viz", kind=EdgeKind.BLOCKS, ts=_TS),
        )
    )
    snap1 = snapshot_from_projection([], graph, seq=1, generated_ts=_TS)
    snap2 = snapshot_from_projection([], graph, seq=1, generated_ts=_TS)
    assert snap1 == snap2
    assert snap1.edges[0].src == "catalyst"  # sorted by src


def test_delta_of_identical_snapshots_is_empty() -> None:
    statuses = [AgentStatus(session="tom", state=State.ACTIVE)]
    prev = snapshot_from_projection(statuses, _graph(), seq=1, generated_ts=_TS)
    curr = snapshot_from_projection(statuses, _graph(), seq=2, generated_ts=_TS)
    batch = delta_between(prev, curr)
    assert batch.deltas == ()
    assert (batch.from_seq, batch.to_seq) == (1, 2)


def test_delta_emits_a_single_upsert_for_a_status_change() -> None:
    prev = snapshot_from_projection(
        [AgentStatus(session="tom", state=State.ACTIVE)], _graph(), seq=1, generated_ts=_TS
    )
    curr = snapshot_from_projection(
        [AgentStatus(session="tom", state=State.BLOCKED, current_task="perm")],
        _graph(),
        seq=2,
        generated_ts=_TS,
    )
    batch = delta_between(prev, curr)
    assert batch.deltas == (
        StatusDelta(
            op=DeltaOp.NODE_UPSERT,
            node=WidgetNode(
                id="tom",
                kind=NodeKind.SESSION,
                status=State.BLOCKED,
                current_task="perm",
            ),
        ),
    )


def test_delta_handles_added_and_removed_nodes() -> None:
    prev = snapshot_from_projection(
        [AgentStatus(session="tom", state=State.ACTIVE)], _graph(), seq=1, generated_ts=_TS
    )
    curr = snapshot_from_projection(
        [AgentStatus(session="catalyst", state=State.ACTIVE)],
        _graph(),
        seq=2,
        generated_ts=_TS,
    )
    ops = {(d.op, d.node.id if d.node else d.node_id) for d in delta_between(prev, curr).deltas}
    assert (DeltaOp.NODE_UPSERT, "catalyst") in ops
    assert (DeltaOp.NODE_REMOVE, "tom") in ops


def test_delta_adds_and_removes_edges_by_identity() -> None:
    edge = InteractionEdge(src="a", dst="b", kind=EdgeKind.DEPENDS_ON, ts=_TS)
    prev = snapshot_from_projection([], _graph(), seq=1, generated_ts=_TS)
    curr = snapshot_from_projection([], _graph(edges=(edge,)), seq=2, generated_ts=_TS)

    added = delta_between(prev, curr).deltas
    assert added == (
        StatusDelta(op=DeltaOp.EDGE_ADD, edge=WidgetEdge("a", "b", EdgeKind.DEPENDS_ON)),
    )
    removed = delta_between(curr, prev).deltas
    assert removed == (
        StatusDelta(op=DeltaOp.EDGE_REMOVE, edge=WidgetEdge("a", "b", EdgeKind.DEPENDS_ON)),
    )


def test_delta_carries_the_recomputed_derived_answers() -> None:
    # A status change shifts who's idle; the batch must ship the fresh derived
    # answers so viz never recomputes the model's query logic itself.
    prev = snapshot_from_projection(
        [AgentStatus(session="tom", state=State.ACTIVE)], _graph(), seq=1, generated_ts=_TS
    )
    curr = snapshot_from_projection(
        [AgentStatus(session="tom", state=State.IDLE, idle_basis=IdleBasis.MEASURED)],
        _graph(),
        seq=2,
        generated_ts=_TS,
    )
    batch = delta_between(prev, curr)
    assert batch.derived.idle == ("tom",)
    assert batch.derived == curr.derived


def test_changed_edge_ref_is_a_remove_plus_add_not_a_mutation() -> None:
    old = InteractionEdge(src="a", dst="b", kind=EdgeKind.REVIEW_OF, ts=_TS, ref="#1")
    new = InteractionEdge(src="a", dst="b", kind=EdgeKind.REVIEW_OF, ts=_TS, ref="#2")
    prev = snapshot_from_projection([], _graph(edges=(old,)), seq=1, generated_ts=_TS)
    curr = snapshot_from_projection([], _graph(edges=(new,)), seq=2, generated_ts=_TS)
    ops = {d.op for d in delta_between(prev, curr).deltas}
    assert ops == {DeltaOp.EDGE_ADD, DeltaOp.EDGE_REMOVE}


def test_delta_carries_the_seq_advance_even_when_empty() -> None:
    snap = snapshot_from_projection([], _graph(), seq=5, generated_ts=_TS)
    later = StatusSnapshot(seq=6, generated_ts=_TS)
    batch = delta_between(snap, later)
    assert batch.deltas == ()
    assert (batch.from_seq, batch.to_seq) == (5, 6)
