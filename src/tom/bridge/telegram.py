"""Mapping a Telegram webhook update into a channel event, and authenticating it.

Telegram delivers updates by **webhook push**: it POSTs an Update object to the
bridge's HTTPS endpoint (set once via ``setWebhook``), so there is no polling.
Two pure pieces live here, the parts worth testing without a live Telegram:

- :func:`channel_event_from_update` turns a raw Update into a
  :class:`~tom.bridge.channel_event.ChannelEvent`. It reads structure only — the
  update type and a handful of salient fields — and never interprets free text;
  the consuming session decides what to do with it.
- :func:`verify_webhook_secret` checks the secret token Telegram echoes in the
  ``X-Telegram-Bot-Api-Secret-Token`` header (configured at ``setWebhook``), so a
  random POST to the public endpoint can't inject a forged update. Compared in
  constant time.

Nothing is ever silently dropped: an update whose type we don't model becomes an
``unknown`` event carrying the keys it presented, so an unhandled type is visible
on the bus rather than lost.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping

from tom.bridge.channel_event import ChannelEvent, ChannelSource

_SUBJECT_PREFIX = "team.event.channel.telegram"

#: The keys a Telegram Update carries exactly one of, besides ``update_id``.
_UPDATE_KINDS = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "callback_query",
    "inline_query",
    "my_chat_member",
    "chat_member",
)
_UNKNOWN_KIND = "unknown"

#: Salient leaf fields lifted from the inner object when present.
_LEAF_FIELDS = ("text", "data", "date", "message_id")


def channel_event_from_update(update: object, *, ts: str) -> ChannelEvent:
    """Map a raw Telegram Update to a :class:`ChannelEvent`.

    ``update`` is typed ``object`` because it arrives as parsed JSON from an
    untrusted POST — the static type guarantees nothing, so we narrow at runtime.
    ``ts`` is the producer's receive stamp, passed in so the function stays pure
    (the Update has no top-level timestamp). Raises if the body isn't a JSON
    object, or if ``update_id`` is missing or not a plain integer — none of those
    is a Telegram Update, and a malformed POST must fail loud rather than publish
    a garbage event.
    """
    if not isinstance(update, Mapping):
        raise ValueError("Telegram update must be a JSON object")
    fields = _as_str_map(update)

    update_id = fields.get("update_id")
    # bool is an int subclass, so an `isinstance(..., int)` check alone would let
    # True/False through as a "valid" id — exclude it explicitly.
    if not isinstance(update_id, int) or isinstance(update_id, bool):
        raise ValueError("Telegram update is missing an integer update_id")

    kind = _kind_of(fields)
    payload = (
        _salient_payload(_as_str_map(fields.get(kind)))
        if kind != _UNKNOWN_KIND
        else {"present_keys": tuple(sorted(k for k in fields if k != "update_id"))}
    )
    return ChannelEvent(
        event_id=f"telegram-{update_id}",
        source=ChannelSource.TELEGRAM,
        kind=kind,
        subject=f"{_SUBJECT_PREFIX}.{kind}",
        ts=ts,
        payload=payload,
    )


def verify_webhook_secret(provided: str | None, expected: str) -> bool:
    """Whether the header secret matches the configured one, in constant time.

    An empty ``expected`` is a misconfiguration (it would accept any caller), so
    it raises rather than waving the request through.
    """
    if expected == "":
        raise ValueError("webhook secret is empty — refusing to authenticate any caller")
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def _kind_of(update: Mapping[str, object]) -> str:
    for key in _UPDATE_KINDS:
        if key in update:
            return key
    return _UNKNOWN_KIND


def _salient_payload(inner: Mapping[str, object]) -> dict[str, object]:
    """Lift the structural fields a session acts on: who, where, and the content.

    Free text rides in ``text`` / ``data`` untouched — carried as data, not read
    for meaning here.
    """
    payload: dict[str, object] = {}

    # The chat sits directly on a message, but a callback_query nests it under its
    # originating `message` — fall back to there so the chat_id needed to route a
    # reply isn't lost on a button press.
    chat = _as_str_map(inner.get("chat"))
    if "id" not in chat:
        chat = _as_str_map(_as_str_map(inner.get("message")).get("chat"))
    if "id" in chat:
        payload["chat_id"] = chat["id"]

    sender = _as_str_map(inner.get("from"))
    if "id" in sender:
        payload["from_id"] = sender["id"]
    if "username" in sender:
        payload["from_username"] = sender["username"]

    for field_name in _LEAF_FIELDS:
        if field_name in inner:
            payload[field_name] = inner[field_name]

    return payload


def _as_str_map(value: object) -> dict[str, object]:
    """Narrow an arbitrary JSON value to a string-keyed map, or ``{}`` if it isn't.

    Rebuilds the mapping so the dynamic value type doesn't leak past this seam —
    everything downstream sees ``object`` and narrows it explicitly.
    """
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(key, str):
            result[key] = item
    return result
