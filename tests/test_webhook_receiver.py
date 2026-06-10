"""The pure webhook handler: auth, parse, map, publish — every path a status."""

from __future__ import annotations

import json
from collections.abc import Mapping

from tom.bridge.publisher import EventPublisher, PublishError
from tom.bridge.receiver import handle_webhook

_TS = "2026-06-09T06:30:00Z"
_SECRET = "s3cret-token"


class _Recorder:
    """Records what it was asked to publish."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def publish(self, subject: str, payload: Mapping[str, object]) -> None:
        self.calls.append((subject, payload))


class _Failing:
    """A publisher whose bus is unavailable."""

    def publish(self, subject: str, payload: Mapping[str, object]) -> None:
        raise PublishError("bus unavailable")


def _message_body() -> bytes:
    update = {
        "update_id": 7,
        "message": {"chat": {"id": 42}, "from": {"id": 1}, "text": "hi"},
    }
    return json.dumps(update).encode("utf-8")


def test_recorder_satisfies_the_publisher_protocol() -> None:
    assert isinstance(_Recorder(), EventPublisher)


def test_good_update_publishes_and_returns_200() -> None:
    rec = _Recorder()
    outcome = handle_webhook(
        _message_body(), _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS
    )
    assert outcome.status == 200
    assert outcome.published is not None
    assert len(rec.calls) == 1
    subject, payload = rec.calls[0]
    assert subject == "team.event.channel.telegram.message"
    assert payload["event_id"] == "telegram-7"
    assert payload["subject"] == subject
    assert payload["ts"] == _TS
    assert isinstance(payload["payload"], dict)
    assert payload["payload"]["chat_id"] == 42


def test_bad_secret_is_401_and_never_publishes() -> None:
    rec = _Recorder()
    outcome = handle_webhook(
        _message_body(), "wrong", expected_secret=_SECRET, publisher=rec, ts=_TS
    )
    assert outcome.status == 401
    assert rec.calls == []


def test_missing_secret_is_401() -> None:
    rec = _Recorder()
    outcome = handle_webhook(
        _message_body(), None, expected_secret=_SECRET, publisher=rec, ts=_TS
    )
    assert outcome.status == 401
    assert rec.calls == []


def test_invalid_json_is_400_and_never_publishes() -> None:
    rec = _Recorder()
    outcome = handle_webhook(
        b"{not json", _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS
    )
    assert outcome.status == 400
    assert rec.calls == []


def test_non_telegram_payload_is_400() -> None:
    rec = _Recorder()
    body = json.dumps({"hello": "world"}).encode("utf-8")  # no update_id
    outcome = handle_webhook(body, _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS)
    assert outcome.status == 400
    assert rec.calls == []


def test_deeply_nested_json_is_400_not_a_crash() -> None:
    # A deeply nested body overflows the JSON parser; it must be a clean 400, not
    # an uncaught RecursionError that escapes the handler.
    rec = _Recorder()
    body = b"[" * 40000 + b"]" * 40000
    outcome = handle_webhook(body, _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS)
    assert outcome.status == 400
    assert rec.calls == []


def test_empty_body_is_400() -> None:
    rec = _Recorder()
    outcome = handle_webhook(b"", _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS)
    assert outcome.status == 400
    assert rec.calls == []


def test_non_utf8_body_is_400_not_a_crash() -> None:
    rec = _Recorder()
    outcome = handle_webhook(
        b"\xff\xfe\x00garbage", _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS
    )
    assert outcome.status == 400
    assert rec.calls == []


def test_json_array_body_is_400() -> None:
    # Valid JSON, but not a Telegram update object — must not publish.
    rec = _Recorder()
    body = json.dumps([{"update_id": 1}]).encode("utf-8")
    outcome = handle_webhook(body, _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS)
    assert outcome.status == 400
    assert rec.calls == []


def test_publish_failure_is_500_so_telegram_retries() -> None:
    outcome = handle_webhook(
        _message_body(), _SECRET, expected_secret=_SECRET, publisher=_Failing(), ts=_TS
    )
    assert outcome.status == 500
    assert outcome.published is None


def test_envelope_carries_the_full_event_shape() -> None:
    rec = _Recorder()
    handle_webhook(_message_body(), _SECRET, expected_secret=_SECRET, publisher=rec, ts=_TS)
    _, payload = rec.calls[0]
    assert set(payload) == {"event_id", "source", "kind", "subject", "ts", "payload"}
    assert payload["source"] == "telegram"
    assert payload["kind"] == "message"
