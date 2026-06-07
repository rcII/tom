"""The sprint board's vocabulary.

The board is a real mutable store — the source of truth the ceremonies read and
the scrum-master moves cards on. Its columns and the closed set of statuses are
defined here so one place owns them. Hand-written for now; it joins the generated
contract registry in a later phase.
"""

from __future__ import annotations

from enum import StrEnum


class BoardStatus(StrEnum):
    """The lanes a card can sit in. The store rejects anything else."""

    NEXT_UP = "next_up"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"


#: The board's required columns on insert. ``points`` / ``link`` / ``note`` /
#: ``sort_key`` are optional and default at the store.
REQUIRED_CARD_FIELDS: tuple[str, ...] = ("title", "project", "assignee", "status")
