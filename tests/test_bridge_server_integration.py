"""End-to-end through a real socket: a POST drives the handler and the publisher.

The server module is thin glue, but glue is where wiring bugs hide — so this
starts the actual ThreadingHTTPServer on an ephemeral port and drives it with a
real HTTP client, asserting the secret check, the path check, and that a good
update reaches the publisher. A recording publisher stands in for NATS.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from http.client import HTTPConnection

import pytest

from tom.bridge.server import BridgeConfig, BridgeServer

_SECRET = "integration-secret"
_PATH = "/telegram/webhook"


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def publish(self, subject: str, payload: Mapping[str, object]) -> None:
        self.calls.append((subject, payload))


@pytest.fixture
def server() -> Iterator[tuple[BridgeServer, _Recorder]]:
    recorder = _Recorder()
    config = BridgeConfig(host="127.0.0.1", port=0, path=_PATH, secret=_SECRET)
    srv = BridgeServer(config, recorder)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, recorder
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _post(srv: BridgeServer, path: str, body: bytes, secret: str | None) -> int:
    host, port = srv.server_address[0], srv.server_address[1]
    conn = HTTPConnection(str(host), int(port), timeout=5)
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    try:
        conn.request("POST", path, body=body, headers=headers)
        return conn.getresponse().status
    finally:
        conn.close()


def _update() -> bytes:
    return json.dumps(
        {"update_id": 99, "message": {"chat": {"id": 7}, "text": "ping"}}
    ).encode("utf-8")


def test_good_post_reaches_the_publisher(server: tuple[BridgeServer, _Recorder]) -> None:
    srv, recorder = server
    assert _post(srv, _PATH, _update(), _SECRET) == 200
    assert len(recorder.calls) == 1
    assert recorder.calls[0][0] == "team.event.channel.telegram.message"


def test_wrong_secret_is_rejected(server: tuple[BridgeServer, _Recorder]) -> None:
    srv, recorder = server
    assert _post(srv, _PATH, _update(), "nope") == 401
    assert recorder.calls == []


def test_wrong_path_is_404(server: tuple[BridgeServer, _Recorder]) -> None:
    srv, recorder = server
    assert _post(srv, "/elsewhere", _update(), _SECRET) == 404
    assert recorder.calls == []
