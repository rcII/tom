"""The in-memory shared-context model.

This binds the two projected views — agent status and the relationship graph —
behind the :class:`~tom.adapters.protocols.StatusGraphRepo` seam and answers the
query verbs against them. It holds the already-projected results; building those
from the durable log is the projector's job, and swapping this in-memory store
for a persistent one later is an adapter change that nothing above this seam
sees.
"""

from __future__ import annotations

from dataclasses import dataclass

from tom import queries
from tom.projection.graph import GraphProjection
from tom.schemas.graph import InteractionEdge, Node
from tom.schemas.status import AgentStatus


@dataclass(frozen=True, slots=True)
class InMemoryStatusGraph:
    """A :class:`StatusGraphRepo` over an in-memory snapshot of the model."""

    graph: GraphProjection
    statuses: tuple[AgentStatus, ...]

    def status_of(self, session: str) -> AgentStatus | None:
        return queries.status_of(self.statuses, session)

    def who_is_idle(self) -> tuple[AgentStatus, ...]:
        return queries.who_is_idle(self.statuses)

    def edges(self) -> tuple[InteractionEdge, ...]:
        return self.graph.edges

    def nodes(self) -> tuple[Node, ...]:
        return self.graph.nodes

    def who_depends_on(self, session: str) -> tuple[str, ...]:
        return queries.who_depends_on(self.graph, session)

    def dependents_of(self, session: str) -> tuple[str, ...]:
        return queries.dependents_of(self.graph, session)

    def who_blocks_whom(self) -> tuple[tuple[str, str], ...]:
        return queries.who_blocks_whom(self.graph)

    def critical_path(self) -> tuple[str, ...]:
        return queries.critical_path(self.graph)
