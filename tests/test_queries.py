"""The query verbs over the shared-context model."""

from __future__ import annotations

from tom import queries
from tom.projection.graph import GraphProjection
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind
from tom.schemas.status import AgentStatus, IdleBasis, State

TS = "2026-06-07T01:00:00-05:00"


def _edge(src: str, dst: str, kind: EdgeKind) -> InteractionEdge:
    return InteractionEdge(src=src, dst=dst, kind=kind, ts=TS, ref=f"{src}->{dst}")


def _graph(*edges: InteractionEdge) -> GraphProjection:
    ids = {edge.src for edge in edges} | {edge.dst for edge in edges}
    nodes = tuple(Node(id=i, kind=NodeKind.SESSION) for i in sorted(ids))
    return GraphProjection(nodes=nodes, edges=edges)


def _status(session: str, state: State) -> AgentStatus:
    basis = IdleBasis.MEASURED if state is State.IDLE else None
    return AgentStatus(session=session, state=state, idle_basis=basis)


# --- status queries ---------------------------------------------------------


def test_who_is_idle_filters_and_sorts() -> None:
    statuses = (
        _status("tom", State.ACTIVE),
        _status("viz", State.IDLE),
        _status("catalyst", State.IDLE),
        _status("oa", State.BLOCKED),
    )
    idle = queries.who_is_idle(statuses)
    assert tuple(status.session for status in idle) == ("catalyst", "viz")


def test_status_of_hit_and_miss() -> None:
    statuses = (_status("tom", State.ACTIVE),)
    assert queries.status_of(statuses, "tom") is not None
    assert queries.status_of(statuses, "ghost") is None


# --- dependency queries -----------------------------------------------------


def test_who_depends_on_and_dependents_of() -> None:
    graph = _graph(
        _edge("api", "db", EdgeKind.DEPENDS_ON),
        _edge("web", "api", EdgeKind.DEPENDS_ON),
        _edge("worker", "db", EdgeKind.DEPENDS_ON),
        _edge("tom", "tpm", EdgeKind.MESSAGE),  # not a dependency; ignored
    )
    assert queries.who_depends_on(graph, "api") == ("db",)
    assert queries.who_depends_on(graph, "db") == ()
    assert queries.dependents_of(graph, "db") == ("api", "worker")
    assert queries.dependents_of(graph, "api") == ("web",)


def test_who_blocks_whom_dedups_and_sorts() -> None:
    graph = _graph(
        _edge("catalyst", "tom", EdgeKind.BLOCKS),
        _edge("oa", "viz", EdgeKind.BLOCKS),
        _edge("catalyst", "tom", EdgeKind.BLOCKS),  # duplicate pair
        _edge("a", "b", EdgeKind.MESSAGE),  # not a block; ignored
    )
    assert queries.who_blocks_whom(graph) == (("catalyst", "tom"), ("oa", "viz"))


# --- critical path ----------------------------------------------------------


def test_critical_path_follows_dependency_precedence() -> None:
    # web depends on api depends on db -> db must finish first, then api, then web.
    graph = _graph(
        _edge("api", "db", EdgeKind.DEPENDS_ON),
        _edge("web", "api", EdgeKind.DEPENDS_ON),
    )
    assert queries.critical_path(graph) == ("db", "api", "web")


def test_critical_path_mixes_blocks_and_depends_on() -> None:
    # build blocks deploy (build before deploy); deploy depends-on test (test before deploy).
    graph = _graph(
        _edge("build", "deploy", EdgeKind.BLOCKS),
        _edge("deploy", "test", EdgeKind.DEPENDS_ON),
    )
    # test -> deploy, build -> deploy; longest single chain is length 2.
    path = queries.critical_path(graph)
    assert len(path) == 2
    assert path[-1] == "deploy"


def test_critical_path_ignores_non_precedence_edges() -> None:
    graph = _graph(
        _edge("tom", "tpm", EdgeKind.MESSAGE),
        _edge("viz", "tom", EdgeKind.REVIEW_OF),
        _edge("a", "b", EdgeKind.HANDS_OFF),
    )
    assert queries.critical_path(graph) == ()


def test_critical_path_breaks_ties_to_smallest_sequence() -> None:
    # Two disjoint length-2 chains; the lexicographically smaller one wins.
    graph = _graph(
        _edge("x", "y", EdgeKind.BLOCKS),
        _edge("b", "c", EdgeKind.BLOCKS),
    )
    assert queries.critical_path(graph) == ("b", "c")


def test_critical_path_is_cycle_safe() -> None:
    # a depends on b and b depends on a — a real cycle. Must terminate and not
    # mis-rank; the back-edge is dropped, leaving a length-2 chain.
    graph = _graph(
        _edge("a", "b", EdgeKind.DEPENDS_ON),
        _edge("b", "a", EdgeKind.DEPENDS_ON),
    )
    path = queries.critical_path(graph)
    assert len(path) == 2
    assert set(path) == {"a", "b"}


def test_critical_path_ignores_self_loop() -> None:
    graph = _graph(_edge("a", "a", EdgeKind.DEPENDS_ON))
    assert queries.critical_path(graph) == ()


def test_critical_path_empty_graph() -> None:
    assert queries.critical_path(GraphProjection(nodes=(), edges=())) == ()


def test_critical_path_longer_chain_beats_a_shorter_one() -> None:
    graph = _graph(
        # a 3-long chain: r -> s -> t
        _edge("s", "r", EdgeKind.DEPENDS_ON),
        _edge("t", "s", EdgeKind.DEPENDS_ON),
        # a 2-long chain that sorts earlier: a -> b
        _edge("b", "a", EdgeKind.DEPENDS_ON),
    )
    assert queries.critical_path(graph) == ("r", "s", "t")
