"""The Telegram-bridge systemd unit is shaped right — and keeps the secret out.

The webhook secret must never live in the unit (it's world-readable and in git);
it comes from an operator-created EnvironmentFile. This checks the non-secret
config is present and parses the way systemd would, that the secret is absent,
and that the supervision directives (EnvironmentFile, Restart=always) are there.
"""

from __future__ import annotations

import shlex
from pathlib import Path

_UNIT = Path(__file__).resolve().parent.parent / "deploy" / "tom-telegram-bridge.service"


def _lines() -> list[str]:
    return _UNIT.read_text(encoding="utf-8").splitlines()


def _systemd_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in _lines():
        if not line.startswith("Environment="):
            continue
        for assignment in shlex.split(line[len("Environment=") :]):
            key, _, value = assignment.partition("=")
            env[key] = value
    return env


def test_nonsecret_config_is_present() -> None:
    env = _systemd_env()
    assert env["TOM_BRIDGE_HOST"] == "127.0.0.1"
    assert env["TOM_BRIDGE_PORT"] == "8788"
    assert env["TOM_BRIDGE_PATH"] == "/telegram/webhook"
    assert env["NATS_URL"].startswith("nats://")


def test_secret_is_not_inlined_in_the_unit() -> None:
    # The token must come from the EnvironmentFile, never an Environment= line.
    assert "TELEGRAM_WEBHOOK_SECRET" not in _systemd_env()
    assert not any(
        line.startswith("Environment=") and "TELEGRAM_WEBHOOK_SECRET" in line
        for line in _lines()
    )


def test_secret_comes_from_an_environment_file() -> None:
    assert any(
        line.startswith("EnvironmentFile=") and "telegram-bridge.env" in line
        for line in _lines()
    )


def test_supervision_directives_present() -> None:
    body = _UNIT.read_text(encoding="utf-8")
    assert "Restart=always" in body
    assert "python -m tom.bridge" in body
    assert "StartLimitBurst=" in body
