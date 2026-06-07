"""The in-memory model satisfies the seam and delegates to the query verbs."""

from __future__ import annotations

from tom.adapters.protocols import StatusGraphRepo
from tom.projection.graph import GraphProjection
from tom.repo import InMemoryStatusGraph
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind
from tom.schemas.status import AgentStatus, State

TS = "2026-06-07T01:00:00-05:00"


def _make_repo() -> InMemoryStatusGraph:
    nodes = (
        Node(id="api", kind=NodeKind.SESSION),
        Node(id="db", kind=NodeKind.SESSION),
        Node(id="web", kind=NodeKind.SESSION),
    )
    edges = (
        InteractionEdge(src="api", dst="db", kind=EdgeKind.DEPENDS_ON, ts=TS, ref="e1"),
        InteractionEdge(src="web", dst="api", kind=EdgeKind.DEPENDS_ON, ts=TS, ref="e2"),
        InteractionEdge(src="db", dst="web", kind=EdgeKind.BLOCKS, ts=TS, ref="e3"),
    )
    statuses = (
        AgentStatus(session="api", state=State.ACTIVE),
        AgentStatus(session="db", state=State.IDLE),
    )
    return InMemoryStatusGraph(graph=GraphProjection(nodes=nodes, edges=edges), statuses=statuses)


def test_satisfies_status_graph_repo_protocol() -> None:
    repo: StatusGraphRepo = _make_repo()
    assert repo.status_of("api") is not None


def test_status_and_graph_accessors_delegate() -> None:
    repo = _make_repo()
    assert repo.status_of("db") is not None
    assert repo.status_of("ghost") is None
    assert tuple(s.session for s in repo.who_is_idle()) == ("db",)
    assert len(tuple(repo.edges())) == 3
    assert tuple(n.id for n in repo.nodes()) == ("api", "db", "web")


def test_dependency_queries_delegate() -> None:
    repo = _make_repo()
    assert repo.who_depends_on("api") == ("db",)
    assert repo.dependents_of("api") == ("web",)
    assert repo.who_blocks_whom() == (("db", "web"),)


def test_critical_path_delegates() -> None:
    repo = _make_repo()
    # db -> api -> web from the depends-on edges; the db->web block is a shorter
    # parallel precedence, so the length-3 chain wins.
    assert repo.critical_path() == ("db", "api", "web")
