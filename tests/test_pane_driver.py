"""The tmux pane driver, against real-shaped tmux output."""

from __future__ import annotations

from tom.wake.pane import PaneDriver, TmuxPaneDriver


class _FakeTmux:
    """Returns scripted stdout per command, recording the argv of each call."""

    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        # keyed by the tmux subcommand (argv[1]); default empty stdout
        self._outputs = outputs or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self._outputs.get(argv[1], "")


def test_satisfies_pane_driver_protocol() -> None:
    driver: PaneDriver = TmuxPaneDriver(run=_FakeTmux())
    assert driver.command_of("7:1") is None  # empty output → not live


def test_command_of_returns_the_running_command() -> None:
    # Real `tmux display-message -p '#{pane_current_command}'` prints the command
    # plus a trailing newline.
    tmux = _FakeTmux({"display-message": "claude\n"})
    driver = TmuxPaneDriver(run=tmux)
    assert driver.command_of("7:1") == "claude"
    assert tmux.calls[0] == [
        "tmux", "display-message", "-t", "7:1", "-p", "#{pane_current_command}",
    ]


def test_command_of_a_shell_pane() -> None:
    # 7:5 on the live rig is a zsh pane — the relay must see it's not claude.
    driver = TmuxPaneDriver(run=_FakeTmux({"display-message": "zsh\n"}))
    assert driver.command_of("7:5") == "zsh"


def test_command_of_dead_target_is_none() -> None:
    # tmux prints an empty line for a target that doesn't resolve.
    driver = TmuxPaneDriver(run=_FakeTmux({"display-message": "\n"}))
    assert driver.command_of("99:99") is None


def test_command_of_when_tmux_is_missing_is_none() -> None:
    def absent(argv: list[str]) -> str:
        raise FileNotFoundError("tmux")

    assert TmuxPaneDriver(run=absent).command_of("7:1") is None


def test_capture_targets_the_pane() -> None:
    tmux = _FakeTmux({"capture-pane": "screen content"})
    assert TmuxPaneDriver(run=tmux).capture("7:1") == "screen content"
    assert tmux.calls[0] == ["tmux", "capture-pane", "-p", "-t", "7:1"]


def test_send_line_sends_literal_text_then_a_separate_carriage_return() -> None:
    tmux = _FakeTmux()
    TmuxPaneDriver(run=tmux).send_line("7:1", "process your inbox")
    # Two calls: literal text, then C-m on its own — never coalesced into one burst.
    assert tmux.calls == [
        ["tmux", "send-keys", "-t", "7:1", "-l", "--", "process your inbox"],
        ["tmux", "send-keys", "-t", "7:1", "C-m"],
    ]
