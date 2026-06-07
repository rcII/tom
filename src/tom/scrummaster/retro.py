"""Drafting the retro.

Same shape as the standup: the facts — what got finished, what's still blocked,
what's carried over — are a pure read of the board, and only the reflection
(what went well, what to improve, suggested next steps) is the local model's,
written from those facts rather than inventing its own. The result is a draft
for a person to take into the actual retro, within the draft-ceremony ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass

from tom.adapters.protocols import BoardRepo
from tom.llm import ChatMessage, LlmClient, Role
from tom.schemas.board import BoardStatus
from tom.scrummaster.authority import Action

_SYSTEM_PROMPT = (
    "You are a team's scrum-master drafting a sprint retro. From the facts given "
    "— what was finished, what is still blocked, what carried over — write a short "
    "reflection: what went well, what to improve, and a few concrete next steps. "
    "Do not invent work that isn't in the facts. Do not estimate or assign points."
)


@dataclass(frozen=True, slots=True)
class RetroFacts:
    """What the board says about the period — no model involved."""

    finished: tuple[str, ...]
    still_blocked: tuple[str, ...]
    carried_over: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Retro:
    action: Action
    facts: RetroFacts
    narrative: str


def gather_facts(board: BoardRepo) -> RetroFacts:
    """Gather the retro's facts by a pure read of the board — no LLM call."""
    return RetroFacts(
        finished=_card_titles(board, BoardStatus.DONE),
        still_blocked=_card_titles(board, BoardStatus.BLOCKED),
        carried_over=_card_titles(board, BoardStatus.IN_PROGRESS),
    )


def render_retro(facts: RetroFacts, llm: LlmClient) -> Retro:
    """Turn gathered facts into a draft retro, reflecting via the local model."""
    messages = [
        ChatMessage(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=Role.USER, content=_facts_as_prompt(facts)),
    ]
    return Retro(action=Action.DRAFT_CEREMONY, facts=facts, narrative=llm.chat(messages))


def generate_retro(board: BoardRepo, llm: LlmClient) -> Retro:
    return render_retro(gather_facts(board), llm)


def _card_titles(board: BoardRepo, status: BoardStatus) -> tuple[str, ...]:
    titles: list[str] = []
    for card in board.cards(status=status):
        title = card.get("title")
        if isinstance(title, str):
            titles.append(title)
    return tuple(titles)


def _facts_as_prompt(facts: RetroFacts) -> str:
    lines = [
        f"Finished: {_join(facts.finished)}",
        f"Still blocked: {_join(facts.still_blocked)}",
        f"Carried over: {_join(facts.carried_over)}",
    ]
    return "\n".join(lines)


def _join(items: tuple[str, ...]) -> str:
    return ", ".join(items) if items else "none"
