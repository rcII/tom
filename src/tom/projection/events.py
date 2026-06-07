"""The events the projector folds.

These are the normalized inputs to the relationship-graph projection: a message
that crossed the bus, and a sub-agent dispatch. They are deliberately small and
immutable — the projection's only job is to fold a stream of them into nodes and
edges, and it must do so the same way every time, so the inputs carry no
mutable state of their own.

The original substrate hands these to us as ``*.msg`` files and JSONL records;
the adapter that reads those is responsible for turning them into these types.
The projection never sees raw bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

#: An immutable empty mapping, safe to share as a default body.
_EMPTY_BODY: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Envelope:
    """A message that crossed the bus.

    ``body`` is kept only so callers can carry the full message; the projection
    never reads it. The edge kind comes from ``subject`` alone — the body is
    untrusted free text and must not be able to name its own relationship.
    """

    message_id: str
    src: str
    dst: str
    subject: str
    ts: str
    body: Mapping[str, object] = field(default=_EMPTY_BODY)


@dataclass(frozen=True, slots=True)
class Dispatch:
    """A sub-agent dispatch — one session handing work to a sub-agent it spawned."""

    subagent_id: str
    requesting_session: str
    ts: str
    ref: str | None = None
