"""The relay loop: wake an idle claude pane only when genuinely-new work arrived.

One pass (``run_once``) walks the configured session→target map. For each it
*resolves* the target to a single specific pane (``_resolve``): a target that
doesn't resolve is skipped, a window holding more than one pane is skipped and
logged loudly (we will not guess which pane the wake was meant for — a window can
hold a session's main pane and, say, a live UAT pane), and a pane that isn't
``claude`` is skipped and logged (a wake line sent to a shell would run as a
command). A window-only address is refused when ambiguous; the operator
disambiguates by configuring the fully-qualified ``session:window.pane``.

For a resolved claude pane it counts the inbox messages newer than that session's
watermark, reads idle, and lets :func:`~tom.wake.relay.decide_wakes` apply the
safety rules. Right before sending it re-resolves the target (defense in depth, so
a pane that changed under us is caught), sends to the resolved ``%N`` pane id, and
advances + persists the watermark.

A session we've not seen is seeded to the relay's baseline (its start time), so
the existing inbox backlog never reads as new. The watermark is the only
timestamp per session — it's both the new-work cutoff and the debounce anchor —
and it's persisted, so a restart neither replays the backlog nor forgets the
debounce.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from tom.wake.inbox import new_message_count
from tom.wake.pane import PaneDriver
from tom.wake.relay import SessionState, WakeDecision, decide_wakes
from tom.wake.watermark import Watermarks

_CLAUDE_COMMAND = "claude"
# A fully-qualified target ends with a ``.<pane-index>`` (e.g. ``7:2.0``); a
# window-only target (``7:2``) does not.
_PANE_QUALIFIED = re.compile(r"\.\d+$")


class IdleDetector(Protocol):
    def is_idle(self, pane_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class CaptureIdleDetector:
    """Idle iff the resolved pane's visible content shows no busy marker.

    ``capture-pane`` reads the *visible* screen of the specific ``%N`` pane, and a
    busy Claude pane shows a live running marker (e.g. ``esc to interrupt``), so a
    stale marker in scrollback can't read as busy. The failure mode is therefore a
    false *busy* (a missed wake, retried next pass), never a false idle that would
    interrupt real work. The markers are configured, not hardcoded, so a TUI
    change is a config tweak.
    """

    driver: PaneDriver
    busy_markers: tuple[str, ...]

    def is_idle(self, pane_id: str) -> bool:
        content = self.driver.capture(pane_id)
        return not any(marker in content for marker in self.busy_markers)


@dataclass(frozen=True, slots=True)
class WakeConfig:
    #: session name → tmux session:window target, e.g. ``{"tpm": "7:1"}``.
    panes: Mapping[str, str]
    inbox_root: Path
    wake_message: str
    debounce: timedelta


class WakeRelay:
    """Drives one wake pass over the configured sessions."""

    def __init__(
        self,
        driver: PaneDriver,
        idle: IdleDetector,
        config: WakeConfig,
        watermarks: Watermarks,
        baseline_ts: str,
    ) -> None:
        self._driver = driver
        self._idle = idle
        self._config = config
        self._watermarks = watermarks
        self._baseline_ts = baseline_ts

    def run_once(self, *, now: str) -> tuple[WakeDecision, ...]:
        states = [
            state
            for session, target in sorted(self._config.panes.items())
            if (state := self._state_of(session, target)) is not None
        ]
        decisions = decide_wakes(states, now=now, debounce=self._config.debounce)
        for decision in decisions:
            # Defense in depth: re-resolve the target in the instant before we
            # send, so a pane that changed (closed, split, became a shell) under
            # us is caught and we never send to the wrong pane.
            pane_id = self._resolve(decision.session, decision.target)
            if pane_id is None:
                continue
            self._driver.send_line(pane_id, self._config.wake_message)
            self._watermarks.set(decision.session, now)
        return decisions

    def _state_of(self, session: str, target: str) -> SessionState | None:
        pane_id = self._resolve(session, target)
        if pane_id is None:
            return None
        watermark = self._watermark_for(session)
        inbox = self._config.inbox_root / f"{session}-inbox"
        return SessionState(
            session=session,
            target=target,
            idle=self._idle.is_idle(pane_id),
            pending=new_message_count(inbox, watermark),
            last_wake_ts=watermark,
        )

    def _resolve(self, session: str, target: str) -> str | None:
        """Resolve a configured target to one specific claude pane's ``%N`` id.

        Returns ``None`` — skipping the session — when the target doesn't resolve,
        when a window-only target holds more than one pane (we won't guess), or
        when the resolved pane isn't ``claude``. The ambiguous and wrong-pane
        cases are logged loudly; a dead/absent target is just skipped.
        """
        panes = self._driver.panes_in(target)
        if not panes:
            return None  # target's window has no panes / doesn't resolve
        if len(panes) > 1 and _PANE_QUALIFIED.search(target) is None:
            self._skip(
                session,
                target,
                f"{len(panes)} panes in the window; refusing to guess — "
                "configure the fully-qualified session:window.pane",
            )
            return None
        pane_id = self._driver.pane_id_of(target)
        chosen = next((pane for pane in panes if pane.id == pane_id), None)
        if chosen is None:
            return None
        if chosen.command != _CLAUDE_COMMAND:
            self._skip(session, target, f"pane is {chosen.command!r}, not claude")
            return None
        return chosen.id

    def _watermark_for(self, session: str) -> str:
        existing = self._watermarks.get(session)
        if existing is not None:
            return existing
        # First time we've seen this session — seed (and persist) its watermark
        # to the relay's start, so the existing backlog never reads as new.
        self._watermarks.set(session, self._baseline_ts)
        return self._baseline_ts

    @staticmethod
    def _skip(session: str, target: str, reason: str) -> None:
        print(f"wake: skipping {session} at {target}: {reason}", file=sys.stderr)
