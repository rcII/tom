"""The wake relay harness: env parsing, config building, and the --once entry."""

from __future__ import annotations

from pathlib import Path

import pytest

from tom.wake.cli import (
    ENV_BUSY_MARKERS,
    ENV_DEBOUNCE,
    ENV_INBOX_ROOT,
    ENV_MESSAGE,
    ENV_PANES,
    ENV_STATE_FILE,
    build_relay,
    config_from_env,
    main,
    parse_busy_markers,
    parse_pane_map,
)
from tom.wake.relay import WakeDecision
from tom.wake.runner import WakeRelay


def test_parse_pane_map_reads_the_team_map() -> None:
    raw = "tpm=7:1,catalyst=7:4,options-analyst=7:2,viz=7:3,tom=7:7"
    assert parse_pane_map(raw) == {
        "tpm": "7:1",
        "catalyst": "7:4",
        "options-analyst": "7:2",
        "viz": "7:3",
        "tom": "7:7",
    }


def test_parse_pane_map_tolerates_whitespace_and_trailing_comma() -> None:
    assert parse_pane_map(" tpm = 7:1 , catalyst=7:4, ") == {"tpm": "7:1", "catalyst": "7:4"}


def test_parse_pane_map_rejects_malformed_entry() -> None:
    with pytest.raises(ValueError, match="not session=pane"):
        parse_pane_map("tpm:7:1")


def test_parse_pane_map_rejects_empty_side() -> None:
    with pytest.raises(ValueError, match="empty session or pane"):
        parse_pane_map("tpm=")


def test_parse_pane_map_rejects_empty_map() -> None:
    with pytest.raises(ValueError, match="lists no panes"):
        parse_pane_map(" , ")


def test_parse_busy_markers() -> None:
    assert parse_busy_markers("esc to interrupt, Running") == ("esc to interrupt", "Running")


def test_config_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_PANES, "tpm=7:1,catalyst=7:4")
    monkeypatch.setenv(ENV_INBOX_ROOT, str(tmp_path))
    monkeypatch.setenv(ENV_MESSAGE, "wake up")
    monkeypatch.setenv(ENV_DEBOUNCE, "120")
    config = config_from_env()
    assert config.panes == {"tpm": "7:1", "catalyst": "7:4"}
    assert config.inbox_root == tmp_path
    assert config.wake_message == "wake up"
    assert config.debounce.total_seconds() == 120


def test_config_from_env_unset_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PANES, raising=False)
    with pytest.raises(ValueError, match="not set"):
        config_from_env()


def test_build_relay_wires_everything_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ENV_PANES, "tpm=7:1")
    monkeypatch.setenv(ENV_INBOX_ROOT, str(tmp_path))
    monkeypatch.setenv(ENV_MESSAGE, "wake up")
    monkeypatch.setenv(ENV_DEBOUNCE, "120")
    monkeypatch.setenv(ENV_BUSY_MARKERS, "esc to interrupt")
    monkeypatch.setenv(ENV_STATE_FILE, str(tmp_path / "state" / "marks.json"))
    # Builds without touching tmux (the driver is constructed, not called).
    assert isinstance(build_relay(), WakeRelay)


def test_build_relay_missing_state_file_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ENV_PANES, "tpm=7:1")
    monkeypatch.setenv(ENV_INBOX_ROOT, str(tmp_path))
    monkeypatch.setenv(ENV_MESSAGE, "wake up")
    monkeypatch.setenv(ENV_DEBOUNCE, "120")
    monkeypatch.setenv(ENV_BUSY_MARKERS, "esc to interrupt")
    monkeypatch.delenv(ENV_STATE_FILE, raising=False)
    with pytest.raises(ValueError, match="not set"):
        build_relay()


class _FakeRelay:
    def __init__(self, decisions: tuple[WakeDecision, ...]) -> None:
        self._decisions = decisions
        self.calls = 0

    def run_once(self, *, now: str) -> tuple[WakeDecision, ...]:
        self.calls += 1
        return self._decisions


def test_main_once_runs_a_single_pass() -> None:
    relay = _FakeRelay((WakeDecision(session="catalyst", target="7:4"),))
    code = main(["--once"], relay_factory=lambda: relay)
    assert code == 0
    assert relay.calls == 1


def test_main_once_with_nothing_to_do() -> None:
    relay = _FakeRelay(())
    assert main(["--once"], relay_factory=lambda: relay) == 0
    assert relay.calls == 1
