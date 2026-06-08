"""Driving tmux panes by session:window target.

A target is a tmux address like ``7:1`` (session ``7``, window ``1``) — the same
form ``send-keys`` and ``capture-pane`` accept, and it resolves to whatever pane
is active in that window. We address by target, not by the server-assigned
``%N`` pane id (which the config can't know ahead of time and which changes
across a tmux restart), and not by pane title (on this rig the title is the
Claude conversation summary, not a stable session name).

``command_of`` is the load-bearing safety check: it tells us both whether a
target is live and what's running there. An idle session's window can be closed
or replaced by a shell, and sending a wake line to a shell would run it as a
command — so the relay calls this and refuses to send to anything that isn't a
``claude`` pane. The send itself is split into literal text then a separate
``C-m``: a carriage return in the same input burst can coalesce into a newline
in the composer, leaving the line sitting unsent.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Protocol

#: Runs an argv and returns its stdout. The seam that keeps tmux testable.
CommandRunner = Callable[[list[str]], str]

# The key that submits a line to a Claude pane — C-m (carriage return), not the
# `Enter` keyname, which the Claude TUI can treat as a newline.
_SUBMIT_KEY = "C-m"


class PaneDriver(Protocol):
    def command_of(self, target: str) -> str | None: ...

    def capture(self, target: str) -> str: ...

    def send_line(self, target: str, text: str) -> None: ...


def _run_tmux(argv: list[str]) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    return completed.stdout


class TmuxPaneDriver:
    """A :class:`PaneDriver` over the ``tmux`` CLI, addressing by session:window."""

    def __init__(self, run: CommandRunner = _run_tmux) -> None:
        self._run = run

    def command_of(self, target: str) -> str | None:
        """The command running at ``target``, or ``None`` if it isn't a live pane.

        tmux prints an empty line for a target that doesn't resolve, so an empty
        result is treated the same as a failed call: not live.
        """
        try:
            output = self._run(
                ["tmux", "display-message", "-t", target, "-p", "#{pane_current_command}"]
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        command = output.strip()
        return command or None

    def capture(self, target: str) -> str:
        return self._run(["tmux", "capture-pane", "-p", "-t", target])

    def send_line(self, target: str, text: str) -> None:
        # Literal text first, then a separate C-m — never both in one burst, or
        # the carriage return can coalesce into a newline and the line sits unsent.
        self._run(["tmux", "send-keys", "-t", target, "-l", "--", text])
        self._run(["tmux", "send-keys", "-t", target, _SUBMIT_KEY])
