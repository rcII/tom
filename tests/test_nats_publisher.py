"""The NATS CLI publisher: argv shape + fail-loud on every CLI failure mode."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from tom.bridge.publisher import (
    NatsCliPublisher,
    PublishError,
    nats_publisher_from_env,
)


def _publisher() -> NatsCliPublisher:
    return NatsCliPublisher(nats_url="nats://h:4222", nats_bin="nats", timeout_seconds=5)


def test_publish_invokes_nats_pub_with_subject_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(list(argv), 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _publisher().publish("team.event.channel.telegram.message", {"b": 2, "a": 1})

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[:5] == ["nats", "pub", "--server", "nats://h:4222",
                        "team.event.channel.telegram.message"]
    # payload is JSON with sorted keys, deterministic on the wire
    assert argv[5] == '{"a": 1, "b": 2}'
    assert captured["kwargs"] == {"check": True, "capture_output": True, "timeout": 5}


def test_called_process_error_becomes_publish_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, list(argv), b"", b"no responders")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PublishError, match="no responders"):
        _publisher().publish("s", {})


def test_missing_cli_becomes_publish_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("nats")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PublishError, match="not found"):
        _publisher().publish("s", {})


def test_timeout_becomes_publish_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(list(argv), 5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PublishError, match="timed out"):
        _publisher().publish("s", {})


def test_factory_reads_nats_url_fail_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NATS_URL", raising=False)
    with pytest.raises(ValueError, match="NATS_URL"):
        nats_publisher_from_env()


def test_factory_builds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NATS_URL", "nats://example:4222")
    monkeypatch.setenv("TOM_BRIDGE_PUBLISH_TIMEOUT_SECONDS", "3")
    publisher = nats_publisher_from_env()
    assert isinstance(publisher, NatsCliPublisher)


def test_malformed_timeout_env_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NATS_URL", "nats://example:4222")
    monkeypatch.setenv("TOM_BRIDGE_PUBLISH_TIMEOUT_SECONDS", "soon")
    with pytest.raises(ValueError, match="must be an integer"):
        nats_publisher_from_env()
