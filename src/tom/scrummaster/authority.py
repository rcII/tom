"""The scrum-master's authority ceiling.

The scrum-master runs on untrusted bus events, so what it is *able* to do is
capped structurally, not by good behavior. Every action it takes is one of these
four, and there is no representation for anything else — no merge, no deploy, no
dvc repro, no money. Adding such a capability would mean adding a member here,
which the ceiling test refuses.
"""

from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    """The only things the scrum-master may do."""

    CARD_MOVE = "card-move"
    DRAFT_CEREMONY = "draft-ceremony"
    TICKET_SUGGEST = "ticket-suggest"
    CHECKIN_NUDGE = "checkin-nudge"


#: The hard ceiling. The scrum-master's whole action surface must be a subset.
AUTHORITY_CEILING: frozenset[Action] = frozenset(Action)
