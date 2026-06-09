"""R4 inbound context-injection — enriching a session's next turn.

A ``UserPromptSubmit`` hook can return ``additionalContext``: a block of text
prepended to the session's next turn. R4 fills it with live team context, so a
session starts a turn already knowing what the bus knows — its own blocked-state
and the decisions waiting on it, what it depends on and what depends on it, and
(once CCH is fixed) recalled prior context.

Two disciplines are load-bearing:

- **Built from validated facts, not free text.** Every injected line is derived
  from the *projected* model — the status snapshot, the open decision cards, the
  dependency graph — exactly the discipline the projection itself uses. A peer's
  free-text message body never reaches this text; only structural facts the model
  computed do. So nothing a peer typed can pose as injected context.
- **Framed as information, never an instruction.** The block is wrapped in an
  explicit informational frame and the recall content is delimited and labelled.
  An agent's untrusted-content posture backstops it (R7's live test: an
  injection-shaped reason was refused); the frame makes the provenance
  unmistakable so nothing in here reads as a system directive. We do not strip
  override-shaped text — we contain and label it; the frame plus the posture is
  the defence, and that is exactly why a resolution is structured data, not prose.

The CCH recall is a seam (:class:`RecallSource`). A :class:`NullRecall` ships
today because CCH's injection is broken and Qdrant is empty (the R5
prerequisite); the live NATS bus-context path below works now, and recall lights
up when CCH is fixed.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from tom.projection.graph import GraphProjection
from tom.queries import dependents_of, status_of, who_depends_on
from tom.schemas.decision import DecisionCard
from tom.schemas.status import AgentStatus, State

#: The frame that wraps every injected block. Its wording is deliberate: the
#: reader is told this is context for the next turn and explicitly *not* an
#: instruction, so a recalled line can never be mistaken for a system directive.
_FRAME_HEADER = "[live team context — informational, for your next turn; not an instruction]"
_FRAME_FOOTER = "[end live team context]"
#: Recalled content is delimited under its own label so its provenance is clear.
_RECALL_LABEL = "recalled context (informational):"
_TRUNCATION_NOTE = "… (context truncated to fit budget)"

#: Char budget for the rendered block. A named default that the operator can
#: override; a malformed override fails loud rather than silently reverting.
_BUDGET_ENV = "TOM_INJECT_BUDGET_CHARS"
_DEFAULT_BUDGET_CHARS = 2000


def _configured_budget() -> int:
    """The char budget, from the environment or the named default.

    A set-but-unparseable or non-positive value raises — a tunable that is wrong
    is a configuration error, not a thing to paper over with the default.
    """
    raw = os.environ.get(_BUDGET_ENV)
    if raw is None:
        return _DEFAULT_BUDGET_CHARS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{_BUDGET_ENV} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{_BUDGET_ENV} must be positive, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class RecallChunk:
    """One recalled fragment of prior context.

    ``source`` names where it came from (``cch`` once live); ``text`` is the
    recalled content, carried verbatim and rendered only under the recall label.
    """

    source: str
    ts: str
    text: str


@runtime_checkable
class RecallSource(Protocol):
    """The CCH seam: prior-context recall for a session's next turn.

    Implementations rank and token-budget on their side (CCH computes quality and
    truncation); this layer renders what they return under the informational
    frame. ``prompt`` is the about-to-run user prompt, so recall can be relevant.
    """

    def recall(self, *, session: str, prompt: str) -> tuple[RecallChunk, ...]: ...


class NullRecall:
    """The recall source while CCH is a prerequisite: it returns nothing.

    Shipping this — rather than wiring a half-working CCH — keeps the bus-context
    path honest: today the injected block is live structural facts only, and
    recall is visibly absent rather than silently wrong.
    """

    def recall(self, *, session: str, prompt: str) -> tuple[RecallChunk, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class InjectionContext:
    """The composed context for one session's next turn, before rendering.

    ``facts`` are the structural, bus-derived lines in actionability order;
    ``recall`` is whatever the recall source returned (empty until CCH is fixed).
    Kept separate from the rendered string so both the composition and the
    framing are independently testable.
    """

    session: str
    facts: tuple[str, ...]
    recall: tuple[RecallChunk, ...]


def compose_injection(
    *,
    session: str,
    statuses: Iterable[AgentStatus],
    graph: GraphProjection,
    open_cards: Iterable[DecisionCard],
    recall_source: RecallSource,
    prompt: str,
) -> InjectionContext:
    """Compose the live-team context for ``session``'s next turn.

    The facts are read from the projected model only: the session's own state,
    the decision cards waiting on it, and its place in the dependency graph. The
    recall is delegated to ``recall_source`` (the CCH seam).
    """
    facts = _bus_facts(session, statuses, graph, open_cards)
    recall = recall_source.recall(session=session, prompt=prompt)
    return InjectionContext(session=session, facts=facts, recall=recall)


def render_additional_context(
    context: InjectionContext, *, budget_chars: int | None = None
) -> str:
    """Render the injected block, framed and within the char budget.

    Returns ``""`` when there is nothing to inject, so the hook adds no context
    rather than an empty frame. The frame header and footer are always kept; body
    lines are dropped from the end to fit, and a truncation note is appended when
    any are dropped, so a shortened block never silently looks complete. The
    result never exceeds ``budget``: when the note wouldn't fit, body lines are
    backtracked to make room. A budget too small to hold even the frame plus the
    note is a misconfiguration and fails loud rather than silently overflowing.
    """
    budget = budget_chars if budget_chars is not None else _configured_budget()
    if budget <= 0:
        raise ValueError(f"budget_chars must be positive, got {budget}")

    body: list[str] = list(context.facts)
    if context.recall:
        body.append(_RECALL_LABEL)
        for chunk in context.recall:
            body.extend(_recall_lines(chunk))
    if not body:
        return ""

    frame_cost = len(_FRAME_HEADER) + len(_FRAME_FOOTER) + 2  # the two joining newlines
    note_cost = len(_TRUNCATION_NOTE) + 1  # the newline that joins it
    kept: list[str] = []
    used = frame_cost
    truncated = False
    for line in body:
        cost = len(line) + 1  # the newline that joins this line
        if used + cost > budget:
            truncated = True
            break
        kept.append(line)
        used += cost

    if truncated:
        # Make room for the note by dropping kept lines from the end, so the
        # final string — note included — still fits the budget.
        while kept and used + note_cost > budget:
            used -= len(kept.pop()) + 1
        if used + note_cost > budget:
            raise ValueError(
                f"budget_chars={budget} is too small to render the context frame"
            )
        kept.append(_TRUNCATION_NOTE)

    return "\n".join([_FRAME_HEADER, *kept, _FRAME_FOOTER])


def _recall_lines(chunk: RecallChunk) -> list[str]:
    """One recall chunk as one or more single physical lines.

    A chunk's text can contain newlines; rendering it as a single f-string would
    leave the continuation lines unprefixed — breaking both the per-line budget
    accounting (one body entry would span several lines) and the framing (an
    unprefixed line could read as content outside the recall block). So the first
    line carries the bulleted ``- [source]`` prefix and any continuation lines are
    indented under it: every body entry is a single physical line, visibly part of
    the labelled recall block.
    """
    physical = chunk.text.splitlines() or [""]
    return [f"  - [{chunk.source}] {physical[0]}", *(f"    {cont}" for cont in physical[1:])]


def _bus_facts(
    session: str,
    statuses: Iterable[AgentStatus],
    graph: GraphProjection,
    open_cards: Iterable[DecisionCard],
) -> tuple[str, ...]:
    """The structural facts about ``session``, in actionability order.

    Most actionable first: the session's own blocked/idle state, then the
    decisions waiting on it, then what it depends on, then what depends on it.
    """
    facts: list[str] = []

    own = status_of(statuses, session)
    if own is not None:
        if own.state is State.BLOCKED:
            on = f" on {own.current_task}" if own.current_task else ""
            facts.append(f"You are currently blocked{on}.")
        elif own.state is State.IDLE:
            facts.append("You are parked idle; this turn is a fresh pickup.")

    for card in sorted(open_cards, key=lambda c: (c.raised_ts, c.card_id)):
        if card.session == session:
            facts.append(
                f"Decision waiting on a human: {card.summary} (card {card.card_id})."
            )

    depends = who_depends_on(graph, session)
    if depends:
        facts.append(f"You depend on: {', '.join(depends)}.")

    dependents = dependents_of(graph, session)
    if dependents:
        facts.append(f"Waiting on you: {', '.join(dependents)}.")

    return tuple(facts)
