"""Re-confirming PR state from gh output."""

from __future__ import annotations

import json

from tom.scrummaster.pr_state import GhPrStateChecker, PrState


def _checker_returning(payload: str) -> GhPrStateChecker:
    return GhPrStateChecker(run=lambda _argv: payload)


def test_merged_is_recognized() -> None:
    checker = _checker_returning(json.dumps({"state": "MERGED"}))
    assert checker.state_of("6") == PrState.MERGED


def test_open_and_closed_are_recognized() -> None:
    assert _checker_returning('{"state": "OPEN"}').state_of("6") == PrState.OPEN
    assert _checker_returning('{"state": "CLOSED"}').state_of("6") == PrState.CLOSED


def test_passes_the_ref_to_gh() -> None:
    seen: list[list[str]] = []

    def runner(argv: list[str]) -> str:
        seen.append(argv)
        return '{"state": "MERGED"}'

    GhPrStateChecker(run=runner).state_of("42")
    assert seen == [["gh", "pr", "view", "42", "--json", "state"]]


def test_unrecognized_state_is_unknown() -> None:
    assert _checker_returning('{"state": "DRAFT"}').state_of("6") == PrState.UNKNOWN


def test_malformed_output_is_unknown() -> None:
    assert _checker_returning("not json").state_of("6") == PrState.UNKNOWN
    assert _checker_returning('"a string"').state_of("6") == PrState.UNKNOWN
    assert _checker_returning("{}").state_of("6") == PrState.UNKNOWN
