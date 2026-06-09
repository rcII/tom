"""The webhook HTTP receiver — a thin adapter over :func:`handle_webhook`.

A supervised process (the systemd unit) runs this: it listens for Telegram's
webhook POSTs, hands each to the pure handler, and answers with the status the
handler returns. Telegram requires HTTPS, so this binds localhost by default and
sits behind a TLS reverse proxy (nginx / caddy) that forwards the webhook path —
the bridge itself stays plain HTTP on the loopback.

Everything decision-shaped lives in :mod:`tom.bridge.receiver`; this module only
moves bytes: read the body, read the secret header, stamp the receive time, call
the handler, write the status back. That keeps the logic testable without a
socket and the socket code too small to hide a bug.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tom.bridge.publisher import EventPublisher
from tom.bridge.receiver import handle_webhook
from tom.config import require_env

_log = logging.getLogger("tom.bridge")

_HOST_ENV = "TOM_BRIDGE_HOST"
_PORT_ENV = "TOM_BRIDGE_PORT"
_PATH_ENV = "TOM_BRIDGE_PATH"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8788
_DEFAULT_PATH = "/telegram/webhook"
_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
# A Telegram update is a few KB; cap the body so a hostile caller can't exhaust
# memory by declaring a huge Content-Length on the public-facing endpoint.
_MAX_BODY_ENV = "TOM_BRIDGE_MAX_BODY_BYTES"
_DEFAULT_MAX_BODY_BYTES = 65536


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """Where the receiver listens and the secret it authenticates with."""

    host: str
    port: int
    path: str
    secret: str
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES


class BridgeServer(ThreadingHTTPServer):
    """An HTTP server carrying the bridge's config and publisher for the handler."""

    def __init__(self, config: BridgeConfig, publisher: EventPublisher) -> None:
        super().__init__((config.host, config.port), _WebhookHandler)
        self.config = config
        self.publisher = publisher


class _WebhookHandler(BaseHTTPRequestHandler):
    """Reads one POST, calls the handler, writes the status back."""

    def do_POST(self) -> None:
        server = self.server
        if not isinstance(server, BridgeServer):
            self._respond(500, "bridge server misconfigured")
            return
        if self.path != server.config.path:
            self._respond(404, "not found")
            return

        length = self._content_length()
        if length > server.config.max_body_bytes:
            # Reject on the declared size before reading a byte of it.
            self._respond(413, "payload too large")
            return

        body = self.rfile.read(length)
        secret = self.headers.get(_SECRET_HEADER)
        ts = datetime.now(UTC).isoformat()
        outcome = handle_webhook(
            body,
            secret,
            expected_secret=server.config.secret,
            publisher=server.publisher,
            ts=ts,
        )
        if outcome.published is not None:
            _log.info("published %s", outcome.published.subject)
        elif outcome.status >= 400:
            _log.warning("webhook %d: %s", outcome.status, outcome.detail)
        self._respond(outcome.status, outcome.detail)

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            return 0
        try:
            length = int(raw)
        except ValueError:
            return 0
        return max(0, length)

    def _respond(self, status: int, detail: str) -> None:
        payload = detail.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        # Route the default access log through our logger at debug, so the
        # outcome logs above are the signal and the per-request line is opt-in.
        _log.debug("%s - %s", self.address_string(), format % args)


def run(config: BridgeConfig, publisher: EventPublisher) -> None:
    """Serve the webhook receiver until the process is stopped."""
    server = BridgeServer(config, publisher)
    _log.info("telegram bridge listening on %s:%d%s", config.host, config.port, config.path)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def bridge_config_from_env() -> BridgeConfig:
    """Resolve the listener config from the environment, fail-loud on the secret."""
    return BridgeConfig(
        host=os.environ.get(_HOST_ENV, _DEFAULT_HOST),
        port=_port_from_env(),
        path=os.environ.get(_PATH_ENV, _DEFAULT_PATH),
        secret=require_env("TELEGRAM_WEBHOOK_SECRET"),
        max_body_bytes=_max_body_from_env(),
    )


def _port_from_env() -> int:
    raw = os.environ.get(_PORT_ENV)
    if raw is None:
        return _DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"{_PORT_ENV} must be an integer, got {raw!r}") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"{_PORT_ENV} must be in 1..65535, got {port}")
    return port


def _max_body_from_env() -> int:
    raw = os.environ.get(_MAX_BODY_ENV)
    if raw is None:
        return _DEFAULT_MAX_BODY_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{_MAX_BODY_ENV} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{_MAX_BODY_ENV} must be positive, got {value}")
    return value
