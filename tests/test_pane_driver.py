"""The tmux pane driver builds the right commands and parses panes."""

from __future__ import annotations

from tom.wake.pane import Pane, PaneDriver, TmuxPaneDriver


class _FakeTmux:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self.output


def test_satisfies_pane_driver_protocol() -> None:
    driver: PaneDriver = TmuxPaneDriver(run=_FakeTmux())
    assert driver.panes() == ()


def test_parses_panes_from_tmux_output() -> None:
    tmux = _FakeTmux("%1\t1\tclaude\ttpm\n%2\t0\tnode\tcatalyst\n")
    panes = TmuxPaneDriver(run=tmux).panes()
    assert panes == (
        Pane(id="%1", active=True, command="claude", title="tpm"),
        Pane(id="%2", active=False, command="node", title="catalyst"),
    )
    assert tmux.calls[0][:3] == ["tmux", "list-panes", "-a"]


def test_blank_lines_are_skipped() -> None:
    tmux = _FakeTmux("%1\t1\tclaude\ttpm\n\n")
    assert len(TmuxPaneDriver(run=tmux).panes()) == 1


def test_capture_uses_the_pane_id() -> None:
    tmux = _FakeTmux("some screen content")
    content = TmuxPaneDriver(run=tmux).capture("%3")
    assert content == "some screen content"
    assert tmux.calls[0] == ["tmux", "capture-pane", "-p", "-t", "%3"]


def test_send_line_submits_the_text_with_carriage_return() -> None:
    tmux = _FakeTmux()
    TmuxPaneDriver(run=tmux).send_line("%3", "you have pending messages")
    # The text is sent followed by C-m (not the Enter keyname), so the idle
    # session reliably submits the turn instead of inserting a newline.
    assert tmux.calls[0] == [
        "tmux", "send-keys", "-t", "%3", "--", "you have pending messages", "C-m",
    ]
