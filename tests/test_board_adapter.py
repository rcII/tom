"""The SQLite board adapter, against a real (in-memory) database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tom.adapters.board import SqliteBoardRepo, create_schema
from tom.adapters.protocols import BoardRepo


def _repo() -> SqliteBoardRepo:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    return SqliteBoardRepo(connection)


def _card(title: str, status: str = "next_up", **extra: object) -> dict[str, object]:
    return {"title": title, "project": "tom", "assignee": "tom", "status": status, **extra}


def test_satisfies_board_repo_protocol() -> None:
    repo: BoardRepo = _repo()
    assert list(repo.cards()) == []


def test_add_then_read_round_trips() -> None:
    repo = _repo()
    card_id = repo.add(_card("write the projector"))
    cards = repo.cards()
    assert len(cards) == 1
    assert cards[0]["id"] == int(card_id)
    assert cards[0]["title"] == "write the projector"
    assert cards[0]["status"] == "next_up"


def test_cards_filter_by_status() -> None:
    repo = _repo()
    repo.add(_card("a", status="next_up"))
    repo.add(_card("b", status="in_progress"))
    in_progress = repo.cards(status="in_progress")
    assert [card["title"] for card in in_progress] == ["b"]


def test_cards_ordered_by_sort_key_then_id() -> None:
    repo = _repo()
    repo.add(_card("late", sort_key=10))
    repo.add(_card("early", sort_key=1))
    titles = [card["title"] for card in repo.cards()]
    assert titles == ["early", "late"]


def test_move_changes_status() -> None:
    repo = _repo()
    card_id = repo.add(_card("ship it"))
    repo.move(card_id, status="in_review")
    assert repo.cards()[0]["status"] == "in_review"


def test_move_unknown_card_fails_loud() -> None:
    repo = _repo()
    with pytest.raises(KeyError, match="no card"):
        repo.move("999", status="done")


def test_move_invalid_status_fails_loud() -> None:
    repo = _repo()
    card_id = repo.add(_card("x"))
    with pytest.raises(ValueError, match="unknown status"):
        repo.move(card_id, status="archived")


def test_move_non_integer_id_fails_loud() -> None:
    repo = _repo()
    with pytest.raises(ValueError, match="not an integer"):
        repo.move("abc", status="done")


def test_add_missing_required_field_fails_loud() -> None:
    repo = _repo()
    with pytest.raises(ValueError, match="missing required field"):
        repo.add({"title": "no project", "assignee": "tom", "status": "next_up"})


def test_add_invalid_status_fails_loud() -> None:
    repo = _repo()
    with pytest.raises(ValueError, match="unknown status"):
        repo.add(_card("x", status="archived"))


def test_add_persists_optional_fields() -> None:
    repo = _repo()
    repo.add(_card("x", points=5, note="watch the cycle case", link="#42"))
    card = repo.cards()[0]
    assert card["points"] == 5
    assert card["note"] == "watch the cycle case"
    assert card["link"] == "#42"


def test_connect_creates_schema_on_disk(tmp_path: Path) -> None:
    db_path = str(tmp_path / "board.sqlite3")
    repo = SqliteBoardRepo.connect(db_path)
    card_id = repo.add(_card("persisted"))
    # A fresh connection to the same file sees the row — it really persisted.
    reopened = SqliteBoardRepo.connect(db_path)
    assert reopened.cards()[0]["id"] == int(card_id)
