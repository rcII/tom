"""Publishing a channel event onto NATS.

The bridge republishes each external-channel update as a NATS event; this is the
seam that does it. :class:`EventPublisher` is the contract, so the webhook handler
depends on an interface (and a recording fake stands in for tests), and
:class:`NatsCliPublisher` is the real one — it shells to the ``nats`` CLI, the
same publish path the rest of the team's tooling uses (the project carries no
Python NATS client). A publish that fails raises :class:`PublishError` rather than
returning quietly, so the handler can answer the webhook with a 5xx and let
Telegram redeliver — a dropped update must never look like a delivered one.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from tom.config import require_env

#: Seconds to wait on the CLI publish before treating it as failed.
_PUBLISH_TIMEOUT_ENV = "TOM_BRIDGE_PUBLISH_TIMEOUT_SECONDS"
_DEFAULT_PUBLISH_TIMEOUT = 10
#: The nats CLI binary; a name resolved on PATH by default, overridable per host.
_NATS_BIN_ENV = "TOM_BRIDGE_NATS_BIN"
_DEFAULT_NATS_BIN = "nats"


class PublishError(RuntimeError):
    """A channel event could not be published to NATS."""


@runtime_checkable
class EventPublisher(Protocol):
    """Publishes one event's JSON payload to a NATS subject."""

    def publish(self, subject: str, payload: Mapping[str, object]) -> None: ...


class NatsCliPublisher:
    """Publishes via the ``nats`` CLI (``nats pub <subject> <json>``)."""

    def __init__(self, *, nats_url: str, nats_bin: str, timeout_seconds: int) -> None:
        self._nats_url = nats_url
        self._nats_bin = nats_bin
        self._timeout_seconds = timeout_seconds

    def publish(self, subject: str, payload: Mapping[str, object]) -> None:
        body = json.dumps(dict(payload), sort_keys=True)
        argv = [self._nats_bin, "pub", "--server", self._nats_url, subject, body]
        try:
            subprocess.run(
                argv,
                check=True,
                capture_output=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise PublishError(f"nats CLI {self._nats_bin!r} not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise PublishError(f"nats publish to {subject} timed out") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", "replace").strip() if exc.stderr else ""
            raise PublishError(f"nats publish to {subject} failed: {stderr}") from exc


def nats_publisher_from_env() -> NatsCliPublisher:
    """Build the publisher from the environment, fail-loud on a missing NATS_URL."""
    return NatsCliPublisher(
        nats_url=require_env("NATS_URL"),
        nats_bin=os.environ.get(_NATS_BIN_ENV, _DEFAULT_NATS_BIN),
        timeout_seconds=_publish_timeout(),
    )


def _publish_timeout() -> int:
    raw = os.environ.get(_PUBLISH_TIMEOUT_ENV)
    if raw is None:
        return _DEFAULT_PUBLISH_TIMEOUT
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{_PUBLISH_TIMEOUT_ENV} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{_PUBLISH_TIMEOUT_ENV} must be positive, got {value}")
    return value
