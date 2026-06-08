"""The persisted wake watermark store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tom.wake.watermark import Watermarks


def test_get_absent_is_none(tmp_path: Path) -> None:
    assert Watermarks(tmp_path / "marks.json").get("tpm") is None


def test_set_then_get(tmp_path: Path) -> None:
    marks = Watermarks(tmp_path / "marks.json")
    marks.set("tpm", "2026-06-08T01:00:00-05:00")
    assert marks.get("tpm") == "2026-06-08T01:00:00-05:00"


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "state" / "marks.json"  # parent dir created on save
    Watermarks(path).set("catalyst", "2026-06-08T02:00:00-05:00")
    # A fresh store over the same file sees it — a restart keeps the watermark.
    assert Watermarks(path).get("catalyst") == "2026-06-08T02:00:00-05:00"


def test_set_updates_existing(tmp_path: Path) -> None:
    path = tmp_path / "marks.json"
    marks = Watermarks(path)
    marks.set("tpm", "2026-06-08T01:00:00-05:00")
    marks.set("tpm", "2026-06-08T03:00:00-05:00")
    assert Watermarks(path).get("tpm") == "2026-06-08T03:00:00-05:00"


def test_malformed_file_fails_loud(tmp_path: Path) -> None:
    path = tmp_path / "marks.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        Watermarks(path)


def test_saved_file_is_a_session_to_timestamp_map(tmp_path: Path) -> None:
    path = tmp_path / "marks.json"
    Watermarks(path).set("viz", "2026-06-08T04:00:00-05:00")
    assert json.loads(path.read_text(encoding="utf-8")) == {"viz": "2026-06-08T04:00:00-05:00"}
