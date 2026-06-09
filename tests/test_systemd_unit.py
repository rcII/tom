"""The systemd unit's Environment= values survive systemd's parsing.

systemd splits an ``Environment=`` directive on whitespace into separate
assignments unless the value is quoted, so an unquoted value with spaces gets
truncated (``TOM_WAKE_MESSAGE=You have …`` becomes just ``You``). This parses the
unit the way systemd does and checks the multi-word values come through whole.
"""

from __future__ import annotations

import shlex
from pathlib import Path

_UNIT = Path(__file__).resolve().parent.parent / "deploy" / "tom-wake.service"
_PREFIX = "Environment="


def _systemd_env() -> dict[str, str]:
    """Parse the unit's Environment= directives as systemd would (quote-aware)."""
    env: dict[str, str] = {}
    for line in _UNIT.read_text(encoding="utf-8").splitlines():
        if not line.startswith(_PREFIX):
            continue
        for assignment in shlex.split(line[len(_PREFIX) :]):
            key, _, value = assignment.partition("=")
            env[key] = value
    return env


def test_message_is_not_truncated_on_a_space() -> None:
    message = _systemd_env()["TOM_WAKE_MESSAGE"]
    # The bug truncated this to "You"; the whole sentence must survive.
    assert message.startswith("You have")
    assert message.endswith("inbox now.")


def test_busy_markers_value_is_whole() -> None:
    assert _systemd_env()["TOM_WAKE_BUSY_MARKERS"] == "esc to interrupt"


def test_no_stray_keys_from_split_values() -> None:
    # If a spaced value had leaked its words as bare assignments, they'd show up
    # as junk keys like "have" or "to". Every key must be a real TOM_WAKE_* one.
    assert all(key.startswith("TOM_WAKE_") for key in _systemd_env())
