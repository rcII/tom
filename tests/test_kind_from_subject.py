"""The edge kind comes from the subject tag and nothing else."""

from __future__ import annotations

import pytest

from tom.projection.kinds import kind_from_subject
from tom.schemas.graph import EdgeKind


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("[blocks] catalyst waiting on the kernel port", EdgeKind.BLOCKS),
        ("[depends-on] tom needs the contracts registry", EdgeKind.DEPENDS_ON),
        ("[review-of] PR #12 status projection", EdgeKind.REVIEW_OF),
        ("[hands-off] passing the bridge port to viz", EdgeKind.HANDS_OFF),
        ("[message] just an fyi", EdgeKind.MESSAGE),
        ("  [blocks] leading whitespace is tolerated", EdgeKind.BLOCKS),
    ],
)
def test_known_leading_tag_sets_kind(subject: str, expected: EdgeKind) -> None:
    assert kind_from_subject(subject) == expected


@pytest.mark.parametrize(
    "subject",
    [
        "tom online — Phase 1 increment 1 starting",
        "⚠️ PEER IDLE: oa",
        "no tag here",
        "[unknown-tag] not a relationship we know",
        "trailing [blocks] tag does not count",
        "",
    ],
)
def test_untagged_or_unknown_falls_back_to_message(subject: str) -> None:
    assert kind_from_subject(subject) == EdgeKind.MESSAGE
