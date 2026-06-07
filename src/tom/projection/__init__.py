"""The event-sourced projection: one log, folded into the shared-context views."""

from __future__ import annotations

from tom.projection.events import Dispatch, Envelope, SignalKind, StatusSignal
from tom.projection.graph import GraphProjection, project_graph
from tom.projection.kinds import kind_from_subject
from tom.projection.status import project_status

__all__ = [
    "Dispatch",
    "Envelope",
    "GraphProjection",
    "SignalKind",
    "StatusSignal",
    "kind_from_subject",
    "project_graph",
    "project_status",
]
