"""Driving tmux panes — always resolved to one specific pane.

A configured address can be a window (``7:2``) or a fully-qualified pane
(``7:2.0``). A window can hold more than one pane, and ``send-keys -t 7:2`` lands
in whichever pane is *active* at that instant — so a wake meant for one session
could inject keystrokes into another (e.g. a live UAT pane sharing the window).
The relay therefore never sends to a window address that has more than one pane;
it resolves to a single ``%N`` pane id and addresses that.

This driver gives it the two pieces it needs to do that safely: ``panes_in``
lists every pane in a target's window (so the relay can refuse an ambiguous one),
and ``pane_id_of`` returns the exact ``%N`` id a target resolves to. ``capture``
and ``send_line`` then act on that ``%N`` id, which names exactly one pane.

``send_line`` sends literal text then a separate ``Enter`` keystroke — kept
separate so the submit can't coalesce into the typed text, and ``Enter`` rather
than ``C-m`` because the composer runs in vim INSERT mode where a raw carriage
return inserts a newline instead of submitting.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

#: Runs an argv and returns its stdout. The seam that keeps tmux testable.
CommandRunner = Callable[[list[str]], str]

# The key that submits a line to a Claude pane. The `Enter` keyname, sent on its
# own after the text. C-m (a raw carriage return) does NOT submit when the
# composer is in vim INSERT mode — it inserts a newline and the line sits unsent,
# verified live. `Enter` submits in that mode; Escape-then-Enter is avoided
# because Escape can clear the composer in a non-vim pane.
_SUBMIT_KEY = "Enter"
_LIST_FORMAT = "#{pane_id}\t#{pane_current_command}"


@dataclass(frozen=True, slots=True)
class Pane:
    """One tmux pane. ``id`` is the ``%N`` id — it addresses exactly one pane."""

    id: str
    command: str


class PaneDriver(Protocol):
    def panes_in(self, target: str) -> tuple[Pane, ...]: ...

    def pane_id_of(self, target: str) -> str | None: ...

    def capture(self, pane_id: str) -> str: ...

    def send_line(self, pane_id: str, text: str) -> None: ...


def _run_tmux(argv: list[str]) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    return completed.stdout


class TmuxPaneDriver:
    """A :class:`PaneDriver` over the ``tmux`` CLI."""

    def __init__(self, run: CommandRunner = _run_tmux) -> None:
        self._run = run

    def panes_in(self, target: str) -> tuple[Pane, ...]:
        """Every pane in ``target``'s window — empty if the target doesn't resolve."""
        try:
            output = self._run(["tmux", "list-panes", "-t", target, "-F", _LIST_FORMAT])
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ()
        panes: list[Pane] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            pane_id, _, command = line.partition("\t")
            panes.append(Pane(id=pane_id, command=command))
        return tuple(panes)

    def pane_id_of(self, target: str) -> str | None:
        """The exact ``%N`` id ``target`` resolves to, or ``None`` if it doesn't.

        For a window target this is the window's active pane; for a fully-qualified
        ``session:window.pane`` it is that specific pane. tmux prints an empty line
        for an unresolvable target, which is treated the same as a failed call.
        """
        try:
            output = self._run(["tmux", "display-message", "-t", target, "-p", "#{pane_id}"])
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        pane_id = output.strip()
        return pane_id or None

    def capture(self, pane_id: str) -> str:
        return self._run(["tmux", "capture-pane", "-p", "-t", pane_id])

    def send_line(self, pane_id: str, text: str) -> None:
        # Literal text first, then a separate Enter — never both in one burst (so
        # the submit can't coalesce into the text), and Enter rather than C-m so
        # the composer in vim INSERT mode actually fires the turn.
        self._run(["tmux", "send-keys", "-t", pane_id, "-l", "--", text])
        self._run(["tmux", "send-keys", "-t", pane_id, _SUBMIT_KEY])
