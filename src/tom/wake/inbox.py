"""Counting a session's *new* pending work.

A wake should fire only for work that arrived since we last looked — not for
everything sitting in the inbox. The naive "every ``*.msg`` is pending" is wrong
here: the bridge renames a message to ``*.processed.*`` only when a script
*replies* to it, so read-and-handled-but-not-replied messages (the common FYI /
ACK / broadcast case) stay bare ``*.msg`` forever, and post-NATS the file-mirror
accumulates unbounded. Counting those would wake every idle pane on every sweep.

So "pending" means *new since a watermark*: a ``*.msg`` whose mtime is later than
the last time we accounted for this session (the last wake, or the relay's start
for a session we've not seen). The watermark is a timestamp the caller persists,
so a restart doesn't replay the whole backlog.
"""

from __future__ import annotations

from pathlib import Path

from tom.projection._time import parse_ts


def new_message_count(inbox_dir: Path, since_ts: str) -> int:
    """How many ``*.msg`` in ``inbox_dir`` are newer than ``since_ts``.

    A missing inbox counts as zero. ``since_ts`` is an ISO-8601 instant; files
    are compared by mtime, so only genuinely-new arrivals count.
    """
    if not inbox_dir.exists():
        return 0
    threshold = parse_ts(since_ts, origin="watermark").timestamp()
    return sum(
        1
        for entry in inbox_dir.glob("*.msg")
        if entry.is_file() and entry.stat().st_mtime > threshold
    )
