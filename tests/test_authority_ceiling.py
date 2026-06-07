"""The scrum-master's authority is capped at four safe actions (AC-21)."""

from __future__ import annotations

from tom.scrummaster.authority import AUTHORITY_CEILING, Action


def test_ceiling_is_exactly_the_four_safe_actions() -> None:
    assert {action.value for action in Action} == {
        "card-move",
        "draft-ceremony",
        "ticket-suggest",
        "checkin-nudge",
    }


def test_ceiling_is_the_whole_action_enum() -> None:
    # The enum IS the ceiling; a new member can't slip in unguarded.
    assert frozenset(Action) == AUTHORITY_CEILING


def test_no_action_expresses_a_forbidden_capability() -> None:
    forbidden = {"merge", "deploy", "dvc", "repro", "pay", "transfer", "push"}
    for action in Action:
        assert action.value not in forbidden
