"""A channel update, on the wire — the event an external channel becomes.

When the bridge receives an update from an external channel, it republishes it as
one of these on NATS, and the session consumes the channel from there. The shape
mirrors the first-party :class:`~tom.schemas.session_event.SessionEvent` (an id,
a source, a kind, a producer-stamped ``ts``, a structural payload), but the
trust posture is the opposite: a channel event is **untrusted external data**.
The bridge transports and structures it; it never interprets the content, and
the consuming session treats the payload as data to decide on, never a command
to obey (RFC-001 AC-7). Keeping that line here is the whole point of routing the
channel through the bus rather than letting it drive a session directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class ChannelSource(StrEnum):
    """Which external channel an event came from."""

    TELEGRAM = "telegram"


_EMPTY_PAYLOAD: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ChannelEvent:
    """One external-channel update, normalized for the bus.

    ``event_id`` is derived from the channel's own update identity so a redelivery
    is the same event (the consumer can dedup). ``kind`` is the update type;
    ``subject`` is the NATS subject it publishes to. ``payload`` carries the
    salient structural fields only — never interpreted here.
    """

    event_id: str
    source: ChannelSource
    kind: str
    subject: str
    ts: str
    payload: Mapping[str, object] = field(default=_EMPTY_PAYLOAD)
