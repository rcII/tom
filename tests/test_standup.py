"""Drafting the standup: facts are deterministic, only the narrative uses the model."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from tom.adapters.board import SqliteBoardRepo, create_schema
from tom.llm import ChatMessage, LlmClient, Role
from tom.projection.graph import GraphProjection
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind
from tom.schemas.status import AgentStatus, IdleBasis, State
from tom.scrummaster.authority import Action
from tom.scrummaster.standup import gather_facts, generate_standup, render_standup

TS = "2026-06-07T01:00:00-05:00"


class _RecordingLlm(LlmClient):
    def __init__(self, reply: str = "Standup: all on track.") -> None:
        self.reply = reply
        self.seen: list[list[ChatMessage]] = []

    def chat(self, messages: Sequence[ChatMessage]) -> str:
        self.seen.append(list(messages))
        return self.reply


def _statuses() -> tuple[AgentStatus, ...]:
    return (
        AgentStatus(session="tom", state=State.ACTIVE),
        AgentStatus(session="catalyst", state=State.BLOCKED),
        AgentStatus(session="oa", state=State.IDLE, idle_basis=IdleBasis.INFERRED_NO_HEARTBEAT),
    )


def _graph() -> GraphProjection:
    nodes = (
        Node(id="api", kind=NodeKind.SESSION),
        Node(id="db", kind=NodeKind.SESSION),
    )
    edges = (InteractionEdge(src="api", dst="db", kind=EdgeKind.DEPENDS_ON, ts=TS, ref="e1"),)
    return GraphProjection(nodes=nodes, edges=edges)


def _board() -> SqliteBoardRepo:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    repo = SqliteBoardRepo(connection)
    repo.add({"title": "projector", "project": "tom", "assignee": "tom", "status": "in_progress"})
    repo.add({"title": "bridge port", "project": "tom", "assignee": "tom", "status": "in_review"})
    repo.add({"title": "stuck thing", "project": "tom", "assignee": "tom", "status": "blocked"})
    return repo


def test_gather_facts_is_deterministic_and_needs_no_model() -> None:
    # No LlmClient is constructed anywhere in this test — facts are a pure walk.
    facts = gather_facts(_statuses(), _graph(), _board())
    assert facts.active == ("tom",)
    assert facts.idle == ("oa",)
    assert facts.blocked == ("catalyst",)
    assert facts.critical_path == ("db", "api")
    assert facts.cards_in_progress == ("projector",)
    assert facts.cards_in_review == ("bridge port",)
    assert facts.cards_blocked == ("stuck thing",)


def test_render_uses_the_model_for_the_narrative_only() -> None:
    facts = gather_facts(_statuses(), _graph(), _board())
    llm = _RecordingLlm(reply="catalyst is blocked; oa idle; tom active.")
    standup = render_standup(facts, llm)

    assert standup.action == Action.DRAFT_CEREMONY
    assert standup.narrative == "catalyst is blocked; oa idle; tom active."
    assert standup.facts == facts
    # The model was given the facts, and a system prompt telling it not to invent.
    assert len(llm.seen) == 1
    sent = llm.seen[0]
    assert sent[0].role == Role.SYSTEM
    assert "Do not estimate" in sent[0].content
    assert "catalyst" in sent[1].content


def test_generate_standup_composes_gather_and_render() -> None:
    llm = _RecordingLlm()
    standup = generate_standup(_statuses(), _graph(), _board(), llm)
    assert standup.facts.blocked == ("catalyst",)
    assert standup.narrative == "Standup: all on track."


def test_empty_team_renders_a_none_filled_prompt() -> None:
    empty_board = SqliteBoardRepo(sqlite3.connect(":memory:"))
    create_schema(empty_board._connection)
    llm = _RecordingLlm()
    standup = generate_standup((), GraphProjection(nodes=(), edges=()), empty_board, llm)
    assert standup.facts.critical_path == ()
    assert "Critical path: none" in llm.seen[0][1].content
