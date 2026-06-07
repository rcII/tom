"""Re-confirming PR state from gh output."""

from __future__ import annotations

import json
import subprocess

from tom.scrummaster.pr_state import GhPrStateChecker, PrState


def _checker_returning(payload: str) -> GhPrStateChecker:
    return GhPrStateChecker(run=lambda _argv: payload)


def _checker_raising(exc: Exception) -> GhPrStateChecker:
    def runner(_argv: list[str]) -> str:
        raise exc

    return GhPrStateChecker(run=runner)


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


def test_gh_nonzero_exit_degrades_to_unknown() -> None:
    # PR-not-found / auth / rate-limit / network — gh exits non-zero. Degrade to
    # UNKNOWN (fail-closed) rather than crashing the caller.
    error = subprocess.CalledProcessError(returncode=1, cmd=["gh"], stderr="not found")
    assert _checker_raising(error).state_of("6") == PrState.UNKNOWN


def test_gh_not_installed_degrades_to_unknown() -> None:
    assert _checker_raising(FileNotFoundError("gh")).state_of("6") == PrState.UNKNOWN
