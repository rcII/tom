"""The dependency canvas renders the shared-context model as readable text."""

from __future__ import annotations

from tom.projection.graph import GraphProjection
from tom.render.canvas import render_dependency_canvas
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind
from tom.schemas.status import AgentStatus, IdleBasis, State

TS = "2026-06-07T01:00:00-05:00"


def _edge(src: str, dst: str, kind: EdgeKind) -> InteractionEdge:
    return InteractionEdge(src=src, dst=dst, kind=kind, ts=TS, ref=f"{src}-{dst}")


def _graph(*edges: InteractionEdge) -> GraphProjection:
    ids = {e.src for e in edges} | {e.dst for e in edges}
    nodes = tuple(Node(id=i, kind=NodeKind.SESSION) for i in sorted(ids))
    return GraphProjection(nodes=nodes, edges=edges)


def _statuses() -> tuple[AgentStatus, ...]:
    return (
        AgentStatus(session="tom", state=State.ACTIVE, current_task="canvas"),
        AgentStatus(session="catalyst", state=State.BLOCKED),
        AgentStatus(
            session="oa", state=State.IDLE, idle_basis=IdleBasis.INFERRED_NO_HEARTBEAT
        ),
    )


def test_agents_section_shows_state_and_task() -> None:
    canvas = render_dependency_canvas(_statuses(), _graph())
    assert "Agents" in canvas
    assert "tom" in canvas and "canvas" in canvas
    assert "blocked" in canvas
    # idle is shown as inferred, never a confident measured idle.
    assert "idle (inferred — no heartbeat)" in canvas


def test_agents_are_ordered_by_session() -> None:
    canvas = render_dependency_canvas(_statuses(), _graph())
    agents_block = canvas.split("\n\n")[0]
    assert agents_block.index("catalyst") < agents_block.index("oa") < agents_block.index("tom")


def test_relationships_grouped_by_kind() -> None:
    graph = _graph(
        _edge("oa", "viz", EdgeKind.BLOCKS),
        _edge("tom", "catalyst", EdgeKind.DEPENDS_ON),
        _edge("viz", "tom", EdgeKind.REVIEW_OF),
    )
    canvas = render_dependency_canvas((), graph)
    assert "blocks:" in canvas
    assert "depends-on:" in canvas
    assert "oa → viz" in canvas
    assert "tom → catalyst" in canvas
    # blocks is listed before depends-on (most urgent first).
    assert canvas.index("blocks:") < canvas.index("depends-on:")


def test_critical_path_is_drawn() -> None:
    graph = _graph(
        _edge("api", "db", EdgeKind.DEPENDS_ON),
        _edge("web", "api", EdgeKind.DEPENDS_ON),
    )
    canvas = render_dependency_canvas((), graph)
    assert "Critical path" in canvas
    assert "db → api → web" in canvas


def test_blocking_section_lists_pairs() -> None:
    graph = _graph(_edge("catalyst", "tom", EdgeKind.BLOCKS))
    canvas = render_dependency_canvas((), graph)
    assert "catalyst blocks tom" in canvas


def test_empty_model_renders_none_markers() -> None:
    canvas = render_dependency_canvas((), GraphProjection(nodes=(), edges=()))
    assert "Agents\n  (none)" in canvas
    assert "Critical path\n  (none)" in canvas


def test_demo_builds_a_coherent_canvas() -> None:
    from examples.dependency_canvas import build_canvas

    canvas = build_canvas()
    # The demo's oa went quiet — it must read as inferred idle.
    assert "oa" in canvas
    assert "idle (inferred — no heartbeat)" in canvas
    # catalyst gates tom via the depends-on edge, so it leads the critical path.
    assert "catalyst → tom" in canvas
    assert "oa blocks viz" in canvas
