"""The tmux pane driver, against real-shaped tmux output."""

from __future__ import annotations

import subprocess

from tom.wake.pane import Pane, PaneDriver, TmuxPaneDriver


class _FakeTmux:
    """Returns scripted stdout per tmux subcommand, recording each argv."""

    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self._outputs = outputs or {}  # keyed by argv[1]
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self._outputs.get(argv[1], "")


def test_satisfies_pane_driver_protocol() -> None:
    driver: PaneDriver = TmuxPaneDriver(run=_FakeTmux())
    assert driver.panes_in("7:1") == ()  # empty output → no panes


def test_panes_in_lists_every_pane_in_the_window() -> None:
    # Real `tmux list-panes -F '#{pane_id}\t#{pane_current_command}'`: one line
    # per pane in the target's window. 7:2 on the live rig has two claude panes.
    tmux = _FakeTmux({"list-panes": "%7\tclaude\n%15\tclaude\n"})
    driver = TmuxPaneDriver(run=tmux)
    assert driver.panes_in("7:2") == (
        Pane(id="%7", command="claude"),
        Pane(id="%15", command="claude"),
    )
    assert tmux.calls[0] == [
        "tmux", "list-panes", "-t", "7:2", "-F", "#{pane_id}\t#{pane_current_command}",
    ]


def test_panes_in_a_shell_window() -> None:
    tmux = _FakeTmux({"list-panes": "%13\tzsh\n"})
    assert TmuxPaneDriver(run=tmux).panes_in("7:5") == (Pane(id="%13", command="zsh"),)


def test_panes_in_dead_target_is_empty() -> None:
    # `tmux list-panes` exits non-zero on a target that doesn't resolve.
    def fail(argv: list[str]) -> str:
        raise subprocess.CalledProcessError(1, argv, stderr="can't find session")

    assert TmuxPaneDriver(run=fail).panes_in("99:99") == ()


def test_pane_id_of_resolves_the_specific_pane() -> None:
    tmux = _FakeTmux({"display-message": "%15\n"})
    driver = TmuxPaneDriver(run=tmux)
    assert driver.pane_id_of("7:2.1") == "%15"
    assert tmux.calls[0] == ["tmux", "display-message", "-t", "7:2.1", "-p", "#{pane_id}"]


def test_pane_id_of_unresolvable_target_is_none() -> None:
    assert TmuxPaneDriver(run=_FakeTmux({"display-message": "\n"})).pane_id_of("99:99") is None


def test_pane_id_of_when_tmux_is_missing_is_none() -> None:
    def absent(argv: list[str]) -> str:
        raise FileNotFoundError("tmux")

    assert TmuxPaneDriver(run=absent).pane_id_of("7:1") is None


def test_capture_addresses_a_specific_pane_id() -> None:
    tmux = _FakeTmux({"capture-pane": "screen content"})
    assert TmuxPaneDriver(run=tmux).capture("%7") == "screen content"
    assert tmux.calls[0] == ["tmux", "capture-pane", "-p", "-t", "%7"]


def test_send_line_sends_literal_text_then_a_separate_carriage_return() -> None:
    tmux = _FakeTmux()
    TmuxPaneDriver(run=tmux).send_line("%7", "process your inbox")
    # Two calls, addressed by %id (one pane): literal text, then C-m on its own.
    assert tmux.calls == [
        ["tmux", "send-keys", "-t", "%7", "-l", "--", "process your inbox"],
        ["tmux", "send-keys", "-t", "%7", "C-m"],
    ]
