"""Drafting the standup.

A standup is two parts kept strictly separate. The *facts* — who is active, idle,
or blocked, where the critical path runs, what's on the board — are gathered by a
plain walk over the projected model, with no model in the loop: they are not the
kind of thing an LLM should be inventing. Only the *narrative*, the readable
summary a person skims, is synthesized by the local model, and it synthesizes
from the facts it is given rather than deciding any of them.

The result is a draft — the draft-ceremony action, within the authority ceiling.
Where it gets written (the vault projection) is a later concern; this produces
the content.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tom import queries
from tom.adapters.protocols import BoardRepo
from tom.llm import ChatMessage, LlmClient, Role
from tom.projection.graph import GraphProjection
from tom.schemas.board import BoardStatus
from tom.schemas.status import AgentStatus, State
from tom.scrummaster.authority import Action

_SYSTEM_PROMPT = (
    "You are a team's scrum-master. Write a short, plain standup summary from the "
    "facts given. Do not invent status, names, or work that isn't in the facts. "
    "Do not estimate or assign points."
)


@dataclass(frozen=True, slots=True)
class StandupFacts:
    """The deterministic ground truth of a standup — no model involved."""

    active: tuple[str, ...]
    idle: tuple[str, ...]
    blocked: tuple[str, ...]
    critical_path: tuple[str, ...]
    cards_in_progress: tuple[str, ...]
    cards_blocked: tuple[str, ...]
    cards_in_review: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Standup:
    action: Action
    facts: StandupFacts
    narrative: str


def gather_facts(
    statuses: Sequence[AgentStatus],
    graph: GraphProjection,
    board: BoardRepo,
) -> StandupFacts:
    """Gather the standup's facts by a pure walk — no LLM call."""
    return StandupFacts(
        active=tuple(s.session for s in statuses if s.state is State.ACTIVE),
        idle=tuple(s.session for s in queries.who_is_idle(statuses)),
        blocked=tuple(s.session for s in statuses if s.state is State.BLOCKED),
        critical_path=queries.critical_path(graph),
        cards_in_progress=_card_titles(board, BoardStatus.IN_PROGRESS),
        cards_blocked=_card_titles(board, BoardStatus.BLOCKED),
        cards_in_review=_card_titles(board, BoardStatus.IN_REVIEW),
    )


def render_standup(facts: StandupFacts, llm: LlmClient) -> Standup:
    """Turn gathered facts into a draft standup, narrating via the local model."""
    messages = [
        ChatMessage(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=Role.USER, content=_facts_as_prompt(facts)),
    ]
    narrative = llm.chat(messages)
    return Standup(action=Action.DRAFT_CEREMONY, facts=facts, narrative=narrative)


def generate_standup(
    statuses: Sequence[AgentStatus],
    graph: GraphProjection,
    board: BoardRepo,
    llm: LlmClient,
) -> Standup:
    return render_standup(gather_facts(statuses, graph, board), llm)


def _card_titles(board: BoardRepo, status: BoardStatus) -> tuple[str, ...]:
    titles: list[str] = []
    for card in board.cards(status=status):
        title = card.get("title")
        if isinstance(title, str):
            titles.append(title)
    return tuple(titles)


def _facts_as_prompt(facts: StandupFacts) -> str:
    lines = [
        f"Active: {_join(facts.active)}",
        f"Idle: {_join(facts.idle)}",
        f"Blocked: {_join(facts.blocked)}",
        f"Critical path: {' -> '.join(facts.critical_path) or 'none'}",
        f"Cards in progress: {_join(facts.cards_in_progress)}",
        f"Cards blocked: {_join(facts.cards_blocked)}",
        f"Cards in review: {_join(facts.cards_in_review)}",
    ]
    return "\n".join(lines)


def _join(items: tuple[str, ...]) -> str:
    return ", ".join(items) if items else "none"
