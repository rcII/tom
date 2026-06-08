"""Driving tmux panes — the mechanism a wake actually rides on.

The team already wakes an idle session by hand with ``tmux send-keys``; this is
that, behind a seam. The driver lists panes, captures a pane's visible content
(to tell idle from busy), and sends a line to a pane (the wake). The real
implementation shells out to ``tmux``; the command runner is injected so the
exact commands are testable without a live tmux server.

This mirrors the already-built tmux-observer MCP's surface (``list_panes`` /
``observe_pane`` / ``send_to_pane``) so the relay can sit on either.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

#: Runs an argv and returns its stdout. The seam that keeps tmux testable.
CommandRunner = Callable[[list[str]], str]

# tmux list-panes format → the fields we parse, tab-separated and in this order.
_PANE_FORMAT = "#{pane_id}\t#{pane_active}\t#{pane_current_command}\t#{pane_title}"

# The key that submits a line to a Claude pane. C-m (carriage return), not the
# `Enter` keyname — in the Claude TUI, Enter can insert a newline rather than
# submit, while C-m reliably submits the turn.
_SUBMIT_KEY = "C-m"


@dataclass(frozen=True, slots=True)
class Pane:
    """A tmux pane and the facts that say whether it's busy."""

    id: str
    active: bool
    command: str
    title: str


class PaneDriver(Protocol):
    def panes(self) -> Sequence[Pane]: ...

    def capture(self, pane_id: str) -> str: ...

    def send_line(self, pane_id: str, text: str) -> None: ...


def _run_tmux(argv: list[str]) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    return completed.stdout


class TmuxPaneDriver:
    """A :class:`PaneDriver` backed by the ``tmux`` CLI."""

    def __init__(self, run: CommandRunner = _run_tmux) -> None:
        self._run = run

    def panes(self) -> tuple[Pane, ...]:
        output = self._run(["tmux", "list-panes", "-a", "-F", _PANE_FORMAT])
        panes: list[Pane] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = [*line.split("\t", 3), "", "", "", ""]
            pane_id, active, command, title = fields[:4]
            panes.append(
                Pane(id=pane_id, active=active == "1", command=command, title=title)
            )
        return tuple(panes)

    def capture(self, pane_id: str) -> str:
        return self._run(["tmux", "capture-pane", "-p", "-t", pane_id])

    def send_line(self, pane_id: str, text: str) -> None:
        # Send the text and submit it (C-m), so an idle session starts a turn.
        self._run(["tmux", "send-keys", "-t", pane_id, "--", text, _SUBMIT_KEY])
