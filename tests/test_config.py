"""Environment resolution fails loud rather than guessing."""

from __future__ import annotations

import pytest

from tom.config import require_env, resolve_env


def test_require_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOM_TEST_VAR", "value")
    assert require_env("TOM_TEST_VAR") == "value"


def test_require_env_unset_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOM_TEST_VAR", raising=False)
    with pytest.raises(ValueError, match="not set"):
        require_env("TOM_TEST_VAR")


def test_require_env_empty_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOM_TEST_VAR", "")
    with pytest.raises(ValueError, match="empty"):
        require_env("TOM_TEST_VAR")


def test_resolve_env_substitutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOM_HOME", "/srv/tom")
    assert resolve_env("${TOM_HOME}/inbox") == "/srv/tom/inbox"


def test_resolve_env_multiple_references(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A", "one")
    monkeypatch.setenv("B", "two")
    assert resolve_env("${A}-${B}") == "one-two"


def test_resolve_env_no_references_is_identity() -> None:
    assert resolve_env("/plain/path") == "/plain/path"


def test_resolve_env_unset_reference_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOM_MISSING", raising=False)
    with pytest.raises(ValueError, match="not set"):
        resolve_env("${TOM_MISSING}/x")


def test_resolve_env_malformed_reference_fails_loud() -> None:
    with pytest.raises(ValueError, match="malformed"):
        resolve_env("${1bad}/x")


def test_resolve_env_unterminated_reference_fails_loud() -> None:
    with pytest.raises(ValueError, match="unresolved"):
        resolve_env("${TOM_HOME/x")
