"""The runnable wake relay — the harness that puts it in production.

Built from the environment (no host values baked into the package) and run two
ways: ``--once`` for a single pass under a systemd timer, or the default looping
service that runs a pass every ``TOM_WAKE_INTERVAL_SECONDS``. The loop is the one
impure shell — it reads the wall clock and sleeps; everything it calls is the
pure, tested core.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from tom.config import require_env
from tom.wake.pane import TmuxPaneDriver
from tom.wake.relay import WakeDecision
from tom.wake.runner import CaptureIdleDetector, WakeConfig, WakeRelay
from tom.wake.watermark import Watermarks


class _Relay(Protocol):
    """What ``main`` needs of a relay — just a pass. Lets a test inject a fake."""

    def run_once(self, *, now: str) -> tuple[WakeDecision, ...]: ...


ENV_PANES = "TOM_WAKE_PANES"
ENV_INBOX_ROOT = "TOM_WAKE_INBOX_ROOT"
ENV_MESSAGE = "TOM_WAKE_MESSAGE"
ENV_DEBOUNCE = "TOM_WAKE_DEBOUNCE_SECONDS"
ENV_BUSY_MARKERS = "TOM_WAKE_BUSY_MARKERS"
ENV_INTERVAL = "TOM_WAKE_INTERVAL_SECONDS"
ENV_STATE_FILE = "TOM_WAKE_STATE_FILE"


def parse_pane_map(raw: str) -> dict[str, str]:
    """Parse ``session=pane,session=pane`` into a map, failing loud on garbage."""
    panes: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"pane map entry {entry!r} is not session=pane")
        session, pane = (part.strip() for part in entry.split("=", 1))
        if not session or not pane:
            raise ValueError(f"pane map entry {entry!r} has an empty session or pane")
        panes[session] = pane
    if not panes:
        raise ValueError(f"{ENV_PANES} lists no panes")
    return panes


def parse_busy_markers(raw: str) -> tuple[str, ...]:
    markers = tuple(marker.strip() for marker in raw.split(",") if marker.strip())
    if not markers:
        raise ValueError(f"{ENV_BUSY_MARKERS} lists no markers")
    return markers


def config_from_env() -> WakeConfig:
    return WakeConfig(
        panes=parse_pane_map(require_env(ENV_PANES)),
        inbox_root=Path(require_env(ENV_INBOX_ROOT)),
        wake_message=require_env(ENV_MESSAGE),
        debounce=timedelta(seconds=float(require_env(ENV_DEBOUNCE))),
    )


def build_relay() -> WakeRelay:
    driver = TmuxPaneDriver()
    detector = CaptureIdleDetector(driver, parse_busy_markers(require_env(ENV_BUSY_MARKERS)))
    watermarks = Watermarks(Path(require_env(ENV_STATE_FILE)))
    # The baseline is captured once, at startup: sessions we've not seen before
    # are accounted for from now, so their existing backlog never reads as new.
    return WakeRelay(driver, detector, config_from_env(), watermarks, baseline_ts=_now())


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _report(decisions: Sequence[WakeDecision]) -> None:
    if decisions:
        print(f"woke {len(decisions)} session(s): " + ", ".join(d.session for d in decisions))
    else:
        print("no sessions needed waking")


def _run_forever(relay: _Relay, interval: float) -> None:
    while True:
        try:
            relay.run_once(now=_now())
        except Exception as exc:
            # Supervisor loop: a transient tmux/IO error shouldn't stop every
            # future wake. Log it loudly (systemd captures stderr) and try again
            # next pass.
            print(f"wake pass failed: {exc}", file=sys.stderr)
        time.sleep(interval)


def main(
    argv: Sequence[str] | None = None,
    *,
    relay_factory: Callable[[], _Relay] = build_relay,
) -> int:
    parser = argparse.ArgumentParser(
        prog="tom-wake",
        description="Wake idle sessions that have pending inter-session messages.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single pass and exit (for a systemd timer)",
    )
    args = parser.parse_args(argv)
    relay = relay_factory()
    if args.once:
        _report(relay.run_once(now=_now()))
        return 0
    _run_forever(relay, float(require_env(ENV_INTERVAL)))
    return 0
