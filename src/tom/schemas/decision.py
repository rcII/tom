"""A decision a human has to make — one store, rendered everywhere.

The jank this kills: a permission prompt or a clarifying question blocks an
interactive session silently in its pane until someone happens to notice. Instead
of a silent block, the thing that needs a human becomes a *card*: it's raised the
moment the session would have blocked, it carries who's waiting and on what, and
it's resolved on a surface a human is actually watching (the console, Telegram,
the board) — never by an inter-session message, which can enqueue a card but
never resolve one.

There is one decision store. The console, the board's needs-human lane, and the
Telegram push leg all render the same cards and the same resolutions; none is a
separate source of truth. A resolution records who, when, what verdict, and on
which surface, so a texted signoff carries the same evidentiary weight as one
clicked in the console.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class DecisionKind(StrEnum):
    """What kind of decision is waiting."""

    #: A tool/permission the session can't take without a human (R1b).
    PERMISSION = "permission"
    #: A clarifying question the session asked (AskUserQuestion and the like).
    INTERACTIVE_PROMPT = "interactive-prompt"
    #: Something that needs EM specifically (a T3 signoff, an SLA breach).
    NEEDS_EM = "needs-em"


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    #: A free-form answer to an interactive prompt (the text rides in the body).
    ANSWERED = "answered"


_EMPTY_DETAIL: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class DecisionCard:
    """A decision raised the instant a session would otherwise have blocked."""

    card_id: str
    session: str
    kind: DecisionKind
    #: The human-facing question, in one line.
    summary: str
    raised_ts: str
    #: The SessionEvent (usually a PermissionRequest) that raised this.
    origin_event_id: str
    detail: Mapping[str, object] = field(default=_EMPTY_DETAIL)


@dataclass(frozen=True, slots=True)
class DecisionResolution:
    """How a card was resolved — the provenance a verdict needs to be trusted."""

    card_id: str
    verdict: Verdict
    #: Who resolved it.
    by: str
    resolved_ts: str
    #: Which surface it was resolved on (console / telegram / board).
    surface: str
    #: A free-form answer or reason; carries the text for an ANSWERED verdict.
    body: str | None = None
