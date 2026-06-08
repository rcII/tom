"""Drafting the retro: facts are a pure board read, only the reflection uses the model."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from tom.adapters.board import SqliteBoardRepo, create_schema
from tom.llm import ChatMessage, LlmClient, Role
from tom.scrummaster.authority import Action
from tom.scrummaster.retro import gather_facts, generate_retro, render_retro


class _RecordingLlm(LlmClient):
    def __init__(self, reply: str = "Went well: shipping. Improve: unblock sooner.") -> None:
        self.reply = reply
        self.seen: list[list[ChatMessage]] = []

    def chat(self, messages: Sequence[ChatMessage]) -> str:
        self.seen.append(list(messages))
        return self.reply


def _board() -> SqliteBoardRepo:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    repo = SqliteBoardRepo(connection)
    repo.add({"title": "projector", "project": "tom", "assignee": "tom", "status": "done"})
    repo.add({"title": "bus port", "project": "tom", "assignee": "tom", "status": "done"})
    repo.add({"title": "stuck thing", "project": "tom", "assignee": "tom", "status": "blocked"})
    repo.add({"title": "half-done", "project": "tom", "assignee": "tom", "status": "in_progress"})
    return repo


def test_gather_facts_is_a_pure_board_read_no_model() -> None:
    facts = gather_facts(_board())
    assert facts.finished == ("projector", "bus port")
    assert facts.still_blocked == ("stuck thing",)
    assert facts.carried_over == ("half-done",)


def test_render_uses_the_model_for_the_reflection_only() -> None:
    facts = gather_facts(_board())
    llm = _RecordingLlm(reply="Solid sprint; unblock faster.")
    retro = render_retro(facts, llm)

    assert retro.action == Action.DRAFT_CEREMONY
    assert retro.narrative == "Solid sprint; unblock faster."
    assert retro.facts == facts
    assert len(llm.seen) == 1
    system, user = llm.seen[0]
    assert system.role == Role.SYSTEM
    assert "Do not estimate" in system.content
    assert "projector" in user.content  # the facts reached the model
    assert "stuck thing" in user.content


def test_generate_composes_gather_and_render() -> None:
    llm = _RecordingLlm()
    retro = generate_retro(_board(), llm)
    assert retro.facts.finished == ("projector", "bus port")
    assert retro.narrative == "Went well: shipping. Improve: unblock sooner."


def test_empty_board_renders_none_filled_facts() -> None:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    llm = _RecordingLlm()
    retro = generate_retro(SqliteBoardRepo(connection), llm)
    assert retro.facts == retro.facts.__class__(finished=(), still_blocked=(), carried_over=())
    assert "Finished: none" in llm.seen[0][1].content
