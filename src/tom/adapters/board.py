"""The sprint board, backed by the existing SQLite store.

This is the v1 :class:`~tom.adapters.protocols.BoardRepo` implementation: it
wraps the ``sprint_board.sqlite3`` the team already runs on. Nothing above the
seam knows it is SQLite; a later store is an adapter swap.

Every write is validated before it touches the database — an unknown status or a
move of a card that doesn't exist is an error, not a silent no-op. The status set
is the store's own ``CHECK`` constraint mirrored in code so the failure is a
clear message rather than a raw SQLite integrity error.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from tom.schemas.board import REQUIRED_CARD_FIELDS, BoardStatus

# Mirrors the store's CHECK constraint exactly, so a fresh deployment and the
# existing board agree on the schema.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    project     TEXT NOT NULL,
    assignee    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN
                  ('next_up','in_progress','blocked','in_review','done')),
    points      INTEGER NOT NULL DEFAULT 0,
    link        TEXT,
    note        TEXT,
    sort_key    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_OPTIONAL_INSERT_FIELDS: tuple[str, ...] = ("points", "link", "note", "sort_key")


def create_schema(connection: sqlite3.Connection) -> None:
    """Create the board table if it isn't there yet (idempotent)."""
    connection.execute(_SCHEMA)
    connection.commit()


class SqliteBoardRepo:
    """A :class:`BoardRepo` over a SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @classmethod
    def connect(cls, path: str) -> SqliteBoardRepo:
        """Open the board at ``path``, creating the table if needed."""
        connection = sqlite3.connect(path)
        create_schema(connection)
        return cls(connection)

    def cards(self, *, status: str | None = None) -> list[Mapping[str, object]]:
        """Return cards, optionally filtered by status, in a stable order."""
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM tasks ORDER BY sort_key, id"
            ).fetchall()
        else:
            self._validate_status(status)
            rows = self._connection.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY sort_key, id", (status,)
            ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def move(self, card_id: str, *, status: str) -> None:
        """Move a card to ``status``; raise if the status or the card is unknown."""
        self._validate_status(status)
        cursor = self._connection.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, self._as_id(card_id)),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"no card with id {card_id!r}")
        self._connection.commit()

    def add(self, card: Mapping[str, object]) -> str:
        """Insert a card and return its new id; raise on a malformed card."""
        for required in REQUIRED_CARD_FIELDS:
            if required not in card:
                raise ValueError(f"card is missing required field {required!r}")
        status = card["status"]
        if not isinstance(status, str):
            raise ValueError("card 'status' must be a string")
        self._validate_status(status)

        columns = list(REQUIRED_CARD_FIELDS)
        values: list[object] = [card[name] for name in REQUIRED_CARD_FIELDS]
        for optional in _OPTIONAL_INSERT_FIELDS:
            if optional in card:
                columns.append(optional)
                values.append(card[optional])

        placeholders = ", ".join("?" for _ in columns)
        cursor = self._connection.execute(
            f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        self._connection.commit()
        new_id = cursor.lastrowid
        if new_id is None:
            raise RuntimeError("insert did not yield a row id")
        return str(new_id)

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in tuple(BoardStatus):
            valid = ", ".join(BoardStatus)
            raise ValueError(f"unknown status {status!r}; expected one of: {valid}")

    @staticmethod
    def _as_id(card_id: str) -> int:
        try:
            return int(card_id)
        except ValueError as exc:
            raise ValueError(f"card id {card_id!r} is not an integer") from exc

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> dict[str, object]:
        # A sqlite3.Row iterates its values, while .keys() gives the column
        # names — zip the two into a plain dict.
        return dict(zip(row.keys(), tuple(row), strict=True))
