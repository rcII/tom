"""The file-mirror event source, against real *.msg files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tom.adapters.bus import (
    ACK_LEDGER_ENV,
    INBOX_DIR_ENV,
    FileMirrorEventSource,
)


def _write_msg(inbox: Path, message_id: str, sender: str = "tpm", subject: str = "hi") -> None:
    envelope = {
        "message_id": message_id,
        "from": sender,
        "to": "tom",
        "subject": subject,
        "timestamp": "2026-06-07T01:00:00-05:00",
        "body": {},
    }
    (inbox / f"{message_id}.msg").write_text(json.dumps(envelope), encoding="utf-8")


def _source(tmp_path: Path) -> FileMirrorEventSource:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return FileMirrorEventSource(inbox_dir=inbox, ack_ledger=tmp_path / "acked.ledger")


def test_reads_messages_from_the_mirror(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write_msg(source._inbox_dir, "20260607T010000_a_tom")
    events = source.events()
    assert len(events) == 1
    assert events[0]["from"] == "tpm"


def test_events_are_ordered_by_filename(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write_msg(source._inbox_dir, "20260607T010200_c_tom")
    _write_msg(source._inbox_dir, "20260607T010000_a_tom")
    _write_msg(source._inbox_dir, "20260607T010100_b_tom")
    ids = [event["message_id"] for event in source.events()]
    assert ids == [
        "20260607T010000_a_tom",
        "20260607T010100_b_tom",
        "20260607T010200_c_tom",
    ]


def test_empty_inbox_yields_nothing(tmp_path: Path) -> None:
    assert _source(tmp_path).events() == []


def test_acked_message_is_skipped(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write_msg(source._inbox_dir, "m1")
    _write_msg(source._inbox_dir, "m2")
    source.ack("m1")
    ids = [event["message_id"] for event in source.events()]
    assert ids == ["m2"]


def test_ack_is_idempotent(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write_msg(source._inbox_dir, "m1")
    source.ack("m1")
    source.ack("m1")
    assert source._ack_ledger.read_text(encoding="utf-8").count("m1") == 1


def test_ack_survives_a_restart(tmp_path: Path) -> None:
    # A fresh source over the same dirs sees the prior ack — the ledger is durable.
    first = _source(tmp_path)
    _write_msg(first._inbox_dir, "m1")
    _write_msg(first._inbox_dir, "m2")
    first.ack("m1")
    second = FileMirrorEventSource(inbox_dir=first._inbox_dir, ack_ledger=first._ack_ledger)
    assert [event["message_id"] for event in second.events()] == ["m2"]


def test_unacked_message_redelivers(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write_msg(source._inbox_dir, "m1")
    assert len(source.events()) == 1
    # Not acked, so it comes back on the next read — at-least-once.
    assert len(source.events()) == 1


def test_malformed_json_fails_loud(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source._inbox_dir / "bad.msg").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        source.events()


def test_non_object_json_fails_loud(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source._inbox_dir / "list.msg").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        source.events()


def test_from_env_resolves_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv(INBOX_DIR_ENV, str(inbox))
    monkeypatch.setenv(ACK_LEDGER_ENV, str(tmp_path / "acked.ledger"))
    source = FileMirrorEventSource.from_env()
    _write_msg(inbox, "m1")
    assert len(source.events()) == 1
