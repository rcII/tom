"""The listener config resolves from the env and fails loud on bad values."""

from __future__ import annotations

import pytest

from tom.bridge.server import bridge_config_from_env


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3cret")


def test_defaults_apply_when_only_the_secret_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    for name in (
        "TOM_BRIDGE_HOST",
        "TOM_BRIDGE_PORT",
        "TOM_BRIDGE_PATH",
        "TOM_BRIDGE_MAX_BODY_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    config = bridge_config_from_env()
    assert config.host == "127.0.0.1"
    assert config.port == 8788
    assert config.path == "/telegram/webhook"
    assert config.max_body_bytes == 65536
    assert config.secret == "s3cret"


def test_missing_secret_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
        bridge_config_from_env()


def test_malformed_port_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("TOM_BRIDGE_PORT", "eighty")
    with pytest.raises(ValueError, match="must be an integer"):
        bridge_config_from_env()


def test_out_of_range_port_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("TOM_BRIDGE_PORT", "70000")
    with pytest.raises(ValueError, match="must be in"):
        bridge_config_from_env()


def test_malformed_max_body_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("TOM_BRIDGE_MAX_BODY_BYTES", "lots")
    with pytest.raises(ValueError, match="must be an integer"):
        bridge_config_from_env()


def test_nonpositive_max_body_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("TOM_BRIDGE_MAX_BODY_BYTES", "0")
    with pytest.raises(ValueError, match="must be positive"):
        bridge_config_from_env()
