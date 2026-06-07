"""Querying the shared-context model.

These are the verbs the scrum-master and any other agent ask of the model: who
is idle, who depends on whom, who is blocking whom, and where the critical path
runs. They are deterministic graph walks over the already-projected status and
graph — no model is in the loop. An agent *consumes* these answers to reason; it
does not compute them with an LLM.

Edge direction convention (the whole query layer leans on it): an edge's ``src``
is the actor and its ``dst`` is the object.

- ``depends-on`` from A to B means **A depends on B** (A needs B).
- ``blocks`` from A to B means **A blocks B** (A is holding up B).

The critical path is the longest precedence chain implied by those two kinds: a
dependency means the thing depended on must come first, a block means the
blocker must come first. The interaction graph can contain cycles (A waits on B
while B waits on A), so the chain is computed on a deterministically acyclic
view — back-edges are dropped, never followed — which both terminates and gives
a stable answer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from tom.projection.graph import GraphProjection
from tom.schemas.graph import EdgeKind
from tom.schemas.status import AgentStatus, State


def who_is_idle(statuses: Iterable[AgentStatus]) -> tuple[AgentStatus, ...]:
    """Every session currently idle, ordered by session name."""
    idle = [status for status in statuses if status.state is State.IDLE]
    return tuple(sorted(idle, key=lambda status: status.session))


def status_of(statuses: Iterable[AgentStatus], session: str) -> AgentStatus | None:
    """The status of one session, or ``None`` if it isn't in the projection."""
    for status in statuses:
        if status.session == session:
            return status
    return None


def who_depends_on(graph: GraphProjection, session: str) -> tuple[str, ...]:
    """What ``session`` depends on — the things it needs, ordered."""
    targets = {
        edge.dst
        for edge in graph.edges
        if edge.kind is EdgeKind.DEPENDS_ON and edge.src == session
    }
    return tuple(sorted(targets))


def dependents_of(graph: GraphProjection, session: str) -> tuple[str, ...]:
    """Who depends on ``session`` — the things that need it, ordered."""
    sources = {
        edge.src
        for edge in graph.edges
        if edge.kind is EdgeKind.DEPENDS_ON and edge.dst == session
    }
    return tuple(sorted(sources))


def who_blocks_whom(graph: GraphProjection) -> tuple[tuple[str, str], ...]:
    """Every ``(blocker, blocked)`` pair, deduplicated and ordered."""
    pairs = {
        (edge.src, edge.dst) for edge in graph.edges if edge.kind is EdgeKind.BLOCKS
    }
    return tuple(sorted(pairs))


def critical_path(graph: GraphProjection) -> tuple[str, ...]:
    """The longest precedence chain over the depends-on and blocks edges.

    Returned earliest-first: each node must complete before the next. Ties in
    length are broken by the lexicographically smallest sequence, so the answer
    is stable. Cycles are broken deterministically, so the walk always
    terminates.
    """
    successors = _precedence_successors(graph)
    nodes = set(successors)
    for later in successors.values():
        nodes.update(later)

    acyclic = _drop_back_edges(successors, nodes)
    return _longest_chain(acyclic, nodes)


def _precedence_successors(graph: GraphProjection) -> dict[str, set[str]]:
    """Map each node to the nodes that must come *after* it.

    A dependency (A needs B) puts B before A; a block (A blocks B) puts A before
    B. Both reduce to one "must complete before" relation.
    """
    successors: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.kind is EdgeKind.DEPENDS_ON:
            earlier, later = edge.dst, edge.src
        elif edge.kind is EdgeKind.BLOCKS:
            earlier, later = edge.src, edge.dst
        else:
            continue
        if earlier != later:
            successors[earlier].add(later)
    return successors


def _drop_back_edges(successors: dict[str, set[str]], nodes: set[str]) -> dict[str, set[str]]:
    """Return a view of ``successors`` with cycle-closing back-edges removed.

    A depth-first walk over the nodes in sorted order keeps every edge except
    those that point back at a node still on the current stack — following one
    of those would close a cycle. Dropping them deterministically yields a DAG.
    """
    color: dict[str, int] = {}  # unvisited (absent) / 1 on-stack / 2 done
    kept: dict[str, set[str]] = defaultdict(set)

    def visit(node: str) -> None:
        color[node] = 1
        for nxt in sorted(successors.get(node, set())):
            state = color.get(nxt, 0)
            if state == 1:
                continue  # back-edge: dropping it breaks the cycle
            kept[node].add(nxt)
            if state == 0:
                visit(nxt)
        color[node] = 2

    for node in sorted(nodes):
        if color.get(node, 0) == 0:
            visit(node)
    return kept


def _longest_chain(acyclic: dict[str, set[str]], nodes: set[str]) -> tuple[str, ...]:
    best: dict[str, tuple[str, ...]] = {}

    def longest_from(node: str) -> tuple[str, ...]:
        cached = best.get(node)
        if cached is not None:
            return cached
        tail: tuple[str, ...] = ()
        for nxt in sorted(acyclic.get(node, set())):
            candidate = longest_from(nxt)
            if _better(candidate, tail):
                tail = candidate
        result = (node, *tail)
        best[node] = result
        return result

    overall: tuple[str, ...] = ()
    for node in sorted(nodes):
        candidate = longest_from(node)
        if _better(candidate, overall):
            overall = candidate
    return overall


def _better(candidate: tuple[str, ...], current: tuple[str, ...]) -> bool:
    """A longer chain wins; equal lengths break to the smaller sequence."""
    if len(candidate) != len(current):
        return len(candidate) > len(current)
    return candidate < current
