"""Suggesting tickets without estimating them (AC-24)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from tom.adapters.board import SqliteBoardRepo, create_schema
from tom.llm import ChatMessage, LlmClient, Role
from tom.scrummaster.authority import AUTHORITY_CEILING, Action
from tom.scrummaster.ticket_suggest import TicketSuggestion, suggest_tickets


class _ScriptedLlm(LlmClient):
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: list[list[ChatMessage]] = []

    def chat(self, messages: Sequence[ChatMessage]) -> str:
        self.seen.append(list(messages))
        return self.reply


def _board() -> SqliteBoardRepo:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    repo = SqliteBoardRepo(connection)
    repo.add({"title": "ship projector", "project": "tom", "assignee": "tom", "status": "done"})
    return repo


def test_parses_one_suggestion_per_line() -> None:
    llm = _ScriptedLlm(
        "Add restart test :: the projector restart path is untested\n"
        "Document the seams :: adapters need a usage example"
    )
    suggestions = suggest_tickets(_board(), llm)
    assert [s.title for s in suggestions] == ["Add restart test", "Document the seams"]
    assert suggestions[0].rationale == "the projector restart path is untested"
    assert all(s.action == Action.TICKET_SUGGEST for s in suggestions)


def test_every_suggestion_needs_a_human() -> None:
    llm = _ScriptedLlm("Fix flaky test :: fails intermittently")
    suggestions = suggest_tickets(_board(), llm)
    assert all(s.needs_human for s in suggestions)


def test_suggestion_cannot_carry_points_even_if_the_model_writes_one() -> None:
    # AC-24: the model puts an estimate in its text. It must never become an
    # authoritative point value — the suggestion has no points field at all, and
    # the number rides along only as inert rationale prose.
    llm = _ScriptedLlm("Fix flaky test :: fails 1 in 5 runs (estimate: 3 points)")
    (suggestion,) = suggest_tickets(_board(), llm)
    assert not hasattr(suggestion, "points")
    assert suggestion.needs_human is True
    assert "3 points" in suggestion.rationale  # inert text, not a field


def test_system_prompt_forbids_estimation() -> None:
    llm = _ScriptedLlm("x :: y")
    suggest_tickets(_board(), llm)
    system = llm.seen[0][0]
    assert system.role == Role.SYSTEM
    assert "Do NOT estimate" in system.content


def test_context_is_the_current_board() -> None:
    llm = _ScriptedLlm("x :: y")
    suggest_tickets(_board(), llm)
    user = llm.seen[0][1]
    assert user.role == Role.USER
    assert "ship projector" in user.content
    assert "[done]" in user.content


def test_lines_without_the_format_are_dropped() -> None:
    llm = _ScriptedLlm(
        "Here are my suggestions:\n"  # preamble, no separator -> dropped
        "\n"  # blank -> dropped
        "Real one :: with a reason"
    )
    suggestions = suggest_tickets(_board(), llm)
    assert len(suggestions) == 1
    assert suggestions[0].title == "Real one"


def test_empty_model_output_yields_no_suggestions() -> None:
    assert suggest_tickets(_board(), _ScriptedLlm("")) == ()


def test_every_suggestion_action_is_within_the_ceiling() -> None:
    llm = _ScriptedLlm("a :: b\nc :: d")
    suggestions = suggest_tickets(_board(), llm)
    assert all(s.action in AUTHORITY_CEILING for s in suggestions)


def test_empty_board_context_is_marked_empty() -> None:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    llm = _ScriptedLlm("x :: y")
    suggest_tickets(SqliteBoardRepo(connection), llm)
    assert "(empty)" in llm.seen[0][1].content


def test_suggestion_is_a_frozen_value() -> None:
    suggestion = TicketSuggestion(
        action=Action.TICKET_SUGGEST, title="t", rationale="r", needs_human=True
    )
    assert suggestion.title == "t"
