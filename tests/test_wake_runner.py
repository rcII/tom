"""The relay loop: resolve to one specific claude pane, wake only on new work."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from tom.wake.pane import Pane
from tom.wake.runner import CaptureIdleDetector, WakeConfig, WakeRelay
from tom.wake.watermark import Watermarks

DEBOUNCE = timedelta(minutes=2)
BUSY_MARKERS = ("esc to interrupt",)
BASELINE = "2026-06-08T01:00:00-05:00"
NOW = "2026-06-08T02:00:00-05:00"
LATER = "2026-06-08T02:03:00-05:00"
WAKE = "You have new messages — process your inbox."


class _FakeDriver:
    """Models tmux: each target's window panes, the id it resolves to, captures."""

    def __init__(
        self,
        windows: dict[str, list[Pane]],
        resolves: dict[str, str],
        captures: dict[str, str],
    ) -> None:
        self._windows = windows  # target → panes in its window
        self._resolves = resolves  # target → the %id it resolves to
        self._captures = captures  # %id → visible content
        self.sent: list[tuple[str, str]] = []

    def panes_in(self, target: str) -> tuple[Pane, ...]:
        return tuple(self._windows.get(target, ()))

    def pane_id_of(self, target: str) -> str | None:
        return self._resolves.get(target)

    def capture(self, pane_id: str) -> str:
        return self._captures.get(pane_id, "")

    def send_line(self, pane_id: str, text: str) -> None:
        self.sent.append((pane_id, text))


def _msg(inbox_root: Path, session: str, name: str, mtime_iso: str) -> None:
    inbox = inbox_root / f"{session}-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_text("{}", encoding="utf-8")
    epoch = datetime.fromisoformat(mtime_iso).timestamp()
    os.utime(path, (epoch, epoch))


def _relay(driver: _FakeDriver, root: Path, panes: dict[str, str]) -> WakeRelay:
    config = WakeConfig(
        panes=panes, inbox_root=root, wake_message=WAKE, debounce=DEBOUNCE
    )
    return WakeRelay(
        driver,
        CaptureIdleDetector(driver, BUSY_MARKERS),
        config,
        Watermarks(root / "marks.json"),
        baseline_ts=BASELINE,
    )


def _single_claude(target: str, pane_id: str, content: str) -> _FakeDriver:
    return _FakeDriver(
        windows={target: [Pane(id=pane_id, command="claude")]},
        resolves={target: pane_id},
        captures={pane_id: content},
    )


def test_idle_single_pane_with_new_work_is_woken(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "$ ")
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})

    decisions = relay.run_once(now=NOW)

    assert len(decisions) == 1
    assert driver.sent == [("%6", WAKE)]


def test_multi_pane_window_only_target_is_refused(tmp_path: Path) -> None:
    # OA's window 7:2 holds two claude panes (main + the live UAT). A window-only
    # target must NOT guess which one — it's skipped, nothing is sent.
    driver = _FakeDriver(
        windows={"7:2": [Pane("%7", "claude"), Pane("%15", "claude")]},
        resolves={"7:2": "%7"},  # would resolve to the active pane — unsafe
        captures={"%7": "$ ", "%15": "$ "},
    )
    _msg(tmp_path, "options-analyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"options-analyst": "7:2"})
    assert relay.run_once(now=NOW) == ()
    assert driver.sent == []


def test_multi_pane_but_fully_qualified_target_resolves(tmp_path: Path) -> None:
    # The operator disambiguated by configuring 7:2.0 — that names the main pane,
    # so it's safe to wake even though the window has two panes.
    driver = _FakeDriver(
        windows={"7:2.0": [Pane("%7", "claude"), Pane("%15", "claude")]},
        resolves={"7:2.0": "%7"},
        captures={"%7": "$ "},
    )
    _msg(tmp_path, "options-analyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"options-analyst": "7:2.0"})
    relay.run_once(now=NOW)
    assert driver.sent == [("%7", WAKE)]


def test_pure_backlog_does_not_wake_anyone(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "$ ")
    for i in range(50):
        _msg(tmp_path, "catalyst", f"old{i}.msg", "2026-06-07T12:00:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    assert relay.run_once(now=NOW) == ()
    assert driver.sent == []


def test_busy_pane_is_not_woken(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "working (esc to interrupt)")
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    assert relay.run_once(now=NOW) == ()


def test_shell_pane_is_skipped(tmp_path: Path) -> None:
    driver = _FakeDriver(
        windows={"7:5": [Pane("%13", "zsh")]},
        resolves={"7:5": "%13"},
        captures={"%13": "$ "},
    )
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:5"})
    assert relay.run_once(now=NOW) == ()
    assert driver.sent == []


def test_dead_target_is_skipped(tmp_path: Path) -> None:
    driver = _FakeDriver(windows={}, resolves={}, captures={})
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    assert relay.run_once(now=NOW) == ()


def test_wake_advances_the_persisted_watermark(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "$ ")
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    relay.run_once(now=NOW)
    assert Watermarks(tmp_path / "marks.json").get("catalyst") == NOW


def test_second_pass_within_debounce_does_not_re_wake(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "$ ")
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})

    first = relay.run_once(now=NOW)
    _msg(tmp_path, "catalyst", "newer.msg", "2026-06-08T02:00:30-05:00")
    second = relay.run_once(now="2026-06-08T02:01:00-05:00")

    assert len(first) == 1
    assert second == ()
    assert len(driver.sent) == 1


def test_re_resolves_before_send_and_skips_a_pane_that_changed(tmp_path: Path) -> None:
    # Single claude pane at state-build, but the window gains a second pane before
    # send → the pre-send re-resolve refuses the now-ambiguous window-only target.
    class _Flipping(_FakeDriver):
        def __init__(self) -> None:
            super().__init__(
                windows={"7:4": [Pane("%6", "claude")]},
                resolves={"7:4": "%6"},
                captures={"%6": "$ "},
            )
            self._calls = 0

        def panes_in(self, target: str) -> tuple[Pane, ...]:
            self._calls += 1
            if self._calls == 1:
                return (Pane("%6", "claude"),)
            return (Pane("%6", "claude"), Pane("%99", "claude"))  # split under us

    driver = _Flipping()
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    relay.run_once(now=NOW)
    assert driver.sent == []


def test_unseen_session_seeds_its_watermark_to_the_baseline(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "$ ")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    relay.run_once(now=NOW)
    assert Watermarks(tmp_path / "marks.json").get("catalyst") == BASELINE


def test_message_after_debounce_wakes_again(tmp_path: Path) -> None:
    driver = _single_claude("7:4", "%6", "$ ")
    _msg(tmp_path, "catalyst", "new.msg", "2026-06-08T01:30:00-05:00")
    relay = _relay(driver, tmp_path, {"catalyst": "7:4"})
    relay.run_once(now=NOW)
    _msg(tmp_path, "catalyst", "newer.msg", "2026-06-08T02:02:00-05:00")
    second = relay.run_once(now=LATER)
    assert len(second) == 1
    assert len(driver.sent) == 2
