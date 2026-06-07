"""The scrum-master's event-processing pass, end to end over fixtures."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from tom.adapters.board import SqliteBoardRepo, create_schema
from tom.adapters.bus import FileMirrorEventSource
from tom.schemas.trust import RejectReason, TrustPolicy
from tom.scrummaster.cards import CardMover
from tom.scrummaster.loop import ScrumMasterLoop
from tom.scrummaster.pr_state import PrState, PrStateChecker

POLICY = TrustPolicy(allowed_senders=frozenset({"tpm", "catalyst"}))


class _FakeBus:
    """A bus whose ack drops the message, like the real durable cursor."""

    def __init__(self, events: Iterable[Mapping[str, object]]) -> None:
        self._events = list(events)
        self.acked: list[str] = []

    def events(self) -> list[Mapping[str, object]]:
        return list(self._events)

    def ack(self, message_id: str) -> None:
        self.acked.append(message_id)
        self._events = [e for e in self._events if e.get("message_id") != message_id]


class _FakePrState(PrStateChecker):
    def __init__(self, state: PrState) -> None:
        self._state = state

    def state_of(self, pr_ref: str) -> PrState:
        return self._state


class _RaisingPrState(PrStateChecker):
    def state_of(self, pr_ref: str) -> PrState:
        raise RuntimeError("gh blew up unexpectedly")


def _wire(message_id: str, sender: str, subject: str, body: object = None) -> dict[str, object]:
    return {
        "message_id": message_id,
        "from": sender,
        "to": "tom",
        "subject": subject,
        "timestamp": "2026-06-07T01:00:00-05:00",
        "body": body if body is not None else {},
    }


def _board_linked_to(pr: str) -> SqliteBoardRepo:
    connection = sqlite3.connect(":memory:")
    create_schema(connection)
    repo = SqliteBoardRepo(connection)
    repo.add(
        {"title": "t", "project": "tom", "assignee": "tom", "status": "in_review", "link": pr}
    )
    return repo


def _loop(bus: _FakeBus, board: SqliteBoardRepo, state: PrState) -> ScrumMasterLoop:
    return ScrumMasterLoop(bus, POLICY, CardMover(board, _FakePrState(state)))


def test_admitted_merge_event_moves_the_card_and_acks() -> None:
    bus = _FakeBus([_wire("m1", "tpm", "[pr-merged] #6")])
    board = _board_linked_to("#6")
    result = _loop(bus, board, PrState.MERGED).run_once()

    assert result.admitted == 1
    assert len(result.moves) == 1
    assert board.cards()[0]["status"] == "done"
    assert bus.acked == ["m1"]


def test_non_allowlisted_event_is_rejected_and_dropped() -> None:
    bus = _FakeBus([_wire("m1", "intruder", "[pr-merged] #6")])
    board = _board_linked_to("#6")
    result = _loop(bus, board, PrState.MERGED).run_once()

    assert result.admitted == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == RejectReason.UNAUTHORIZED
    assert result.moves == ()
    assert board.cards()[0]["status"] == "in_review"  # untouched
    assert bus.acked == ["m1"]  # dropped, won't be reprocessed


def test_malformed_event_is_rejected_and_dropped() -> None:
    malformed = _wire("m1", "tpm", "[pr-merged] #6")
    del malformed["subject"]
    bus = _FakeBus([malformed])
    result = _loop(bus, _board_linked_to("#6"), PrState.MERGED).run_once()

    assert result.admitted == 0
    assert result.rejected[0].reason == RejectReason.MALFORMED
    assert bus.acked == ["m1"]


def test_mixed_batch_processes_each_message() -> None:
    bus = _FakeBus(
        [
            _wire("m1", "tpm", "[pr-merged] #6"),
            _wire("m2", "intruder", "[pr-merged] #6"),
            _wire("m3", "catalyst", "just chatting"),  # admitted, no card action
        ]
    )
    result = _loop(bus, _board_linked_to("#6"), PrState.MERGED).run_once()

    assert result.admitted == 2  # tpm + catalyst
    assert len(result.rejected) == 1  # intruder
    assert len(result.moves) == 1  # only the merge event moved a card
    assert sorted(bus.acked) == ["m1", "m2", "m3"]


def test_a_handler_crash_leaves_the_message_unacked_for_redelivery() -> None:
    # at-least-once: handle runs before ack, so a crash mid-handle means the
    # message is NOT acked and will come back on the next pass.
    bus = _FakeBus([_wire("m1", "tpm", "[pr-merged] #6")])
    mover = CardMover(_board_linked_to("#6"), _RaisingPrState())
    loop = ScrumMasterLoop(bus, POLICY, mover)

    with pytest.raises(RuntimeError, match="gh blew up"):
        loop.run_once()
    assert bus.acked == []  # nothing acked — m1 will be redelivered


def test_integration_with_the_file_mirror_source(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for mid, sender in (("a", "tpm"), ("b", "catalyst")):
        (inbox / f"{mid}.msg").write_text(
            json.dumps(_wire(mid, sender, "[pr-merged] #6")), encoding="utf-8"
        )
    source = FileMirrorEventSource(inbox_dir=inbox, ack_ledger=tmp_path / "acked.ledger")
    board = _board_linked_to("#6")
    loop = ScrumMasterLoop(source, POLICY, CardMover(board, _FakePrState(PrState.MERGED)))

    first = loop.run_once()
    assert first.admitted == 2
    # Both acked to the durable ledger — a second pass sees nothing new.
    second = loop.run_once()
    assert second.admitted == 0
    assert second.moves == ()
