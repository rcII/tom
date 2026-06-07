"""The seams.

The team-ops layer never reaches for a concrete store, bus, or vault directly.
It depends only on these four Protocols. v1 implementations wrap whatever
substrate is already running; later ones swap in the typed core. Nothing above
these interfaces changes when that happens — that contract is the reason the
layers can move independently.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from tom.schemas.graph import InteractionEdge, Node
from tom.schemas.status import AgentStatus


class BoardRepo(Protocol):
    """The kanban board, as a source of truth the ceremonies read and write."""

    def cards(self, *, status: str | None = None) -> Iterable[Mapping[str, object]]: ...

    def move(self, card_id: str, *, status: str) -> None: ...

    def add(self, card: Mapping[str, object]) -> str: ...


class BusClient(Protocol):
    """The message bus. Inbound events are data the receiver may act on — never
    a command. Implementations differ in *how* events arrive; the contract that
    they are at-least-once and replayable on restart does not."""

    def events(self) -> Iterable[Mapping[str, object]]: ...

    def publish(self, subject: str, body: Mapping[str, object]) -> None: ...

    def ack(self, message_id: str) -> None: ...


class BrainQuery(Protocol):
    """The vault, queried as a knowledge graph. Structured questions resolve by
    a plain graph walk; only genuinely semantic ones reach for a model."""

    def query(self, *, where: Mapping[str, object]) -> Iterable[Mapping[str, object]]: ...

    def neighbors(self, node_id: str, *, relation: str) -> Iterable[str]: ...


class StatusGraphRepo(Protocol):
    """The shared-context model: every agent's current status plus the live
    relationship graph, both rebuilt deterministically from the durable log."""

    def status_of(self, session: str) -> AgentStatus | None: ...

    def who_is_idle(self) -> Iterable[AgentStatus]: ...

    def edges(self) -> Iterable[InteractionEdge]: ...

    def nodes(self) -> Iterable[Node]: ...
