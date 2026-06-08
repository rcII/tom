"""Suggesting tickets — and declining to estimate them.

The scrum-master can propose tickets from what it sees on the board, but it does
not point them. A confident estimate on a small board anchors the humans into
rubber-stamping it, so the discipline is the gate-21 one: propose, mark
needs-human, and stop short of guessing a number. That stop is structural here —
a :class:`TicketSuggestion` has no points field to carry an estimate, and the
generator never extracts one. If the model writes "(3 points)" into its
rationale, that text rides along as prose; it never becomes an authoritative
estimate.

Like the standup, the context is gathered deterministically (the current board);
only the suggestions themselves are the model's, and they are drafts for a human.
"""

from __future__ import annotations

from dataclasses import dataclass

from tom.adapters.protocols import BoardRepo
from tom.llm import ChatMessage, LlmClient, Role
from tom.scrummaster.authority import Action

_SEPARATOR = " :: "
_SYSTEM_PROMPT = (
    "You are a team's scrum-master. From the current board, suggest tickets worth "
    "opening — gaps, follow-ups, missing tests. Output one ticket per line as "
    "'title :: rationale', with no preamble. Do NOT estimate points, effort, or "
    "size — a human will."
)


@dataclass(frozen=True, slots=True)
class TicketSuggestion:
    """A proposed ticket — never an authoritative one, and never pointed.

    There is deliberately no ``points`` field: a suggestion the scrum-master
    declines to estimate cannot carry an estimate, so no code path can write one.
    """

    action: Action
    title: str
    rationale: str
    needs_human: bool


def suggest_tickets(board: BoardRepo, llm: LlmClient) -> tuple[TicketSuggestion, ...]:
    """Propose tickets from the current board — each a needs-human draft."""
    messages = [
        ChatMessage(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        ChatMessage(role=Role.USER, content=_board_context(board)),
    ]
    return _parse_suggestions(llm.chat(messages))


def _board_context(board: BoardRepo) -> str:
    lines = ["Current board:"]
    for card in board.cards():
        title = card.get("title")
        status = card.get("status")
        if isinstance(title, str) and isinstance(status, str):
            lines.append(f"- [{status}] {title}")
    if len(lines) == 1:
        lines.append("(empty)")
    return "\n".join(lines)


def _parse_suggestions(text: str) -> tuple[TicketSuggestion, ...]:
    suggestions: list[TicketSuggestion] = []
    for line in text.splitlines():
        if _SEPARATOR not in line:
            # Not a suggestion in the asked-for format (a preamble or blank line);
            # drop it rather than emit a garbage ticket.
            continue
        title, rationale = line.split(_SEPARATOR, 1)
        title = title.strip()
        if not title:
            continue
        suggestions.append(
            TicketSuggestion(
                action=Action.TICKET_SUGGEST,
                title=title,
                rationale=rationale.strip(),
                needs_human=True,
            )
        )
    return tuple(suggestions)
