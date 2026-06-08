"""Counting only *new* messages — the backlog of read-but-unreplied .msg is not work."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from tom.wake.inbox import new_message_count

WATERMARK = "2026-06-08T01:00:00-05:00"


def _msg(inbox: Path, name: str, mtime_iso: str) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_text("{}", encoding="utf-8")
    epoch = datetime.fromisoformat(mtime_iso).timestamp()
    os.utime(path, (epoch, epoch))


def test_counts_only_messages_newer_than_the_watermark(tmp_path: Path) -> None:
    inbox = tmp_path / "catalyst-inbox"
    # The backlog: read-but-unreplied messages older than the watermark.
    _msg(inbox, "old1.msg", "2026-06-07T20:00:00-05:00")
    _msg(inbox, "old2.msg", "2026-06-08T00:30:00-05:00")
    # Genuinely new arrivals after the watermark.
    _msg(inbox, "new1.msg", "2026-06-08T01:30:00-05:00")
    _msg(inbox, "new2.msg", "2026-06-08T01:45:00-05:00")
    assert new_message_count(inbox, WATERMARK) == 2


def test_a_pure_backlog_counts_as_zero(tmp_path: Path) -> None:
    # The live failure: 925 bare .msg files, all old → must NOT read as pending.
    inbox = tmp_path / "tpm-inbox"
    for i in range(5):
        _msg(inbox, f"old{i}.msg", "2026-06-07T12:00:00-05:00")
    assert new_message_count(inbox, WATERMARK) == 0


def test_processed_files_are_never_counted(tmp_path: Path) -> None:
    inbox = tmp_path / "catalyst-inbox"
    _msg(inbox, "a.msg.processed.1779414367", "2026-06-08T01:30:00-05:00")  # newer, but processed
    assert new_message_count(inbox, WATERMARK) == 0


def test_missing_inbox_is_zero(tmp_path: Path) -> None:
    assert new_message_count(tmp_path / "never-seen-inbox", WATERMARK) == 0
