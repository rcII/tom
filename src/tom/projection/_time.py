"""Timestamp parsing shared by the projections.

Both folds order events by time, and both need that ordering to be a function
of the timestamps alone — never of the machine's local zone. So a timestamp
without an offset is rejected rather than silently localized, and anything
unparseable fails loud rather than sorting wrong.
"""

from __future__ import annotations

from datetime import datetime


def parse_ts(ts: str, *, origin: str) -> datetime:
    """Parse an ISO-8601 instant, failing loud on anything we can't order.

    ``origin`` names where the timestamp came from, so a failure points at the
    offending event rather than just the bad string.
    """
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp {ts!r} on {origin}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {ts!r} on {origin} has no timezone offset")
    return parsed
