"""The webhook request, handled — pure, so it tests without a socket.

``handle_webhook`` is the whole decision: authenticate the caller, parse the
body, map it to a channel event, publish it. It returns a :class:`WebhookOutcome`
(an HTTP status + what it did) rather than touching the wire, so every path —
a forged caller, a junk body, a non-Telegram payload, a publish failure — is a
plain assertion in a test. The HTTP server is a thin adapter over this.

The status codes are chosen so Telegram does the right thing: 200 on success,
401 for a bad secret and 400 for an unparseable/!Telegram body (Telegram should
not retry those — they will never parse), and 500 when the publish itself fails
(Telegram *should* retry — the update was valid, the bus was briefly unavailable).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from tom.bridge.channel_event import ChannelEvent
from tom.bridge.publisher import EventPublisher, PublishError
from tom.bridge.telegram import channel_event_from_update, verify_webhook_secret


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    """What handling a webhook produced: the HTTP status, the event (if one was
    published), and a short human-readable reason for logs."""

    status: int
    published: ChannelEvent | None
    detail: str


def handle_webhook(
    body: bytes,
    secret_header: str | None,
    *,
    expected_secret: str,
    publisher: EventPublisher,
    ts: str,
) -> WebhookOutcome:
    """Authenticate, parse, map, and publish one webhook POST.

    Never raises for an expected failure — each becomes a status. A
    :class:`PublishError` is turned into a 500 so the caller retries; only a
    genuinely unexpected error would propagate.
    """
    if not verify_webhook_secret(secret_header, expected_secret):
        return WebhookOutcome(401, None, "unauthorized: bad or missing secret token")

    try:
        parsed: object = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return WebhookOutcome(400, None, "bad request: body is not valid JSON")
    except RecursionError:
        # Deeply nested JSON (within the body cap) overflows the parser; that's
        # abusive input, not a transient — 400 so Telegram doesn't retry it.
        return WebhookOutcome(400, None, "bad request: JSON nested too deeply")

    try:
        event = channel_event_from_update(parsed, ts=ts)
    except ValueError as exc:
        return WebhookOutcome(400, None, f"bad request: not a Telegram update ({exc})")

    try:
        publisher.publish(event.subject, _envelope(event))
    except PublishError as exc:
        return WebhookOutcome(500, None, f"publish failed: {exc}")

    return WebhookOutcome(200, event, "ok")


def _envelope(event: ChannelEvent) -> dict[str, object]:
    """The event as the JSON envelope published to NATS — the same fields a
    consumer of the bus reads, with ``payload`` carried whole."""
    return {
        "event_id": event.event_id,
        "source": event.source.value,
        "kind": event.kind,
        "subject": event.subject,
        "ts": event.ts,
        "payload": dict(event.payload),
    }
