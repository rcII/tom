"""Re-confirming a pull request's real state through ``gh``.

When a bus message claims a PR merged, the scrum-master never takes the message's
word for it — it asks ``gh`` directly. This is the seam for that ask: a checker
the card-mover calls, with a real implementation that shells out to ``gh pr view``
and a command runner injected so the parsing is testable without the network.

The scrum-master only ever *reads* PR state here. There is no path that merges,
closes, or otherwise mutates a PR — that authority is outside the ceiling.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

#: Runs an argv and returns its stdout. The seam that makes ``gh`` testable.
CommandRunner = Callable[[list[str]], str]


class PrState(StrEnum):
    MERGED = "merged"
    OPEN = "open"
    CLOSED = "closed"
    #: gh didn't return a state we recognize (or the PR is unknown).
    UNKNOWN = "unknown"


# gh reports state in upper case; map only the states we recognize.
_GH_STATE: dict[str, PrState] = {
    "MERGED": PrState.MERGED,
    "OPEN": PrState.OPEN,
    "CLOSED": PrState.CLOSED,
}


class PrStateChecker(Protocol):
    def state_of(self, pr_ref: str) -> PrState: ...


def _run_gh(argv: list[str]) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    return completed.stdout


class GhPrStateChecker:
    """A :class:`PrStateChecker` backed by ``gh pr view``."""

    def __init__(self, run: CommandRunner = _run_gh) -> None:
        self._run = run

    def state_of(self, pr_ref: str) -> PrState:
        output = self._run(["gh", "pr", "view", pr_ref, "--json", "state"])
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return PrState.UNKNOWN
        if not isinstance(payload, dict):
            return PrState.UNKNOWN
        state = payload.get("state")
        if not isinstance(state, str):
            return PrState.UNKNOWN
        return _GH_STATE.get(state, PrState.UNKNOWN)
