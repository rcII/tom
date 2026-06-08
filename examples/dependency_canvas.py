"""Runnable demo: sample bus events → projections → the dependency canvas.

Run with ``python -m examples.dependency_canvas`` (or ``python
examples/dependency_canvas.py``). It builds a small, made-up team out of the same
event types the real bus carries, folds them through the real projectors, and
prints the shared-context model as the dependency canvas — the whole mesh at a
glance.
"""

from __future__ import annotations

from datetime import timedelta

from tom.projection.events import Dispatch, Envelope, SignalKind, StatusSignal
from tom.projection.graph import project_graph
from tom.projection.status import project_status
from tom.render.canvas import render_dependency_canvas

_NOW = "2026-06-07T12:00:00-05:00"
_IDLE_TTL = timedelta(minutes=10)


def _events() -> list[Envelope | Dispatch]:
    return [
        Envelope(
            "m1", "tom", "catalyst",
            "[depends-on] need the kernel port", "2026-06-07T11:55:00-05:00",
        ),
        Envelope("m2", "oa", "viz", "[blocks] holding the schema", "2026-06-07T11:56:00-05:00"),
        Envelope("m3", "viz", "tom", "[review-of] PR #14", "2026-06-07T11:57:00-05:00"),
        Envelope("m4", "tom", "catalyst", "quick question", "2026-06-07T11:58:00-05:00"),
        Dispatch("20260607T115900_tom_a1b2", "tom", "2026-06-07T11:59:00-05:00"),
    ]


def _signals() -> list[StatusSignal]:
    return [
        StatusSignal(
            "tom", "2026-06-07T11:59:00-05:00", SignalKind.STARTED, task="dependency canvas"
        ),
        StatusSignal("catalyst", "2026-06-07T11:58:00-05:00", SignalKind.BLOCKED, task="ci fix"),
        StatusSignal("viz", "2026-06-07T11:57:00-05:00", SignalKind.STARTED, task="review #14"),
        # oa started long ago and went quiet — inferred idle, not measured.
        StatusSignal("oa", "2026-06-07T11:00:00-05:00", SignalKind.STARTED, task="long backtest"),
    ]


def build_canvas() -> str:
    graph = project_graph(_events())
    statuses = project_status(_signals(), now=_NOW, idle_ttl=_IDLE_TTL)
    return render_dependency_canvas(statuses, graph)


def main() -> None:
    print(build_canvas())


if __name__ == "__main__":
    main()
