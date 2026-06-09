"""Panel reconciliation: the blocking re-class, fail-loud guards, surfacing."""

from __future__ import annotations

import pytest

from tom.review.reconcile import reconcile
from tom.schemas.review import Decision, Finding, ReviewVerdict, Severity

_PR = "#29"
_HEAD = "9c3c166"


def _verdict(
    lens: str,
    decision: Decision,
    *,
    findings: tuple[Finding, ...] = (),
    confidence: float = 1.0,
    pr: str = _PR,
    head: str = _HEAD,
) -> ReviewVerdict:
    return ReviewVerdict(
        pr=pr, lens=lens, head_sha=head, decision=decision,
        findings=findings, confidence=confidence,
    )


def test_all_approve_no_findings_is_approve() -> None:
    result = reconcile(_PR, [_verdict("a", Decision.APPROVE), _verdict("b", Decision.APPROVE)])
    assert result.overall is Decision.APPROVE
    assert result.escalated is False
    assert result.blocking_findings == ()


def test_an_explicit_request_changes_is_not_an_escalation() -> None:
    result = reconcile(
        _PR, [_verdict("a", Decision.APPROVE), _verdict("b", Decision.REQUEST_CHANGES)]
    )
    assert result.overall is Decision.REQUEST_CHANGES
    assert result.escalated is False  # a reviewer's own headline said it


def test_a_blocking_finding_reclasses_an_otherwise_approving_panel() -> None:
    # The pillar catch: a reviewer cited a blocker but stamped APPROVE.
    blocker = Finding(severity=Severity.BLOCKING, file="server.py", claim="unbounded read", line=70)
    result = reconcile(
        _PR,
        [
            _verdict("security", Decision.APPROVE, findings=(blocker,)),
            _verdict("correctness", Decision.APPROVE),
        ],
    )
    assert result.overall is Decision.REQUEST_CHANGES
    assert result.escalated is True
    assert result.blocking_findings == (blocker,)


def test_non_blocking_findings_with_comment_is_comment() -> None:
    nit = Finding(severity=Severity.NIT, file="x.py", claim="rename")
    result = reconcile(
        _PR,
        [_verdict("a", Decision.COMMENT, findings=(nit,)), _verdict("b", Decision.APPROVE)],
    )
    assert result.overall is Decision.COMMENT
    assert result.escalated is False


def test_low_confidence_verdicts_are_surfaced() -> None:
    shaky = _verdict("a", Decision.APPROVE, confidence=0.3)
    result = reconcile(_PR, [shaky, _verdict("b", Decision.APPROVE)])
    assert result.low_confidence == (shaky,)


def test_empty_panel_fails_loud() -> None:
    with pytest.raises(ValueError, match="empty panel"):
        reconcile(_PR, [])


def test_verdict_for_a_different_pr_fails_loud() -> None:
    with pytest.raises(ValueError, match="verdicts for"):
        reconcile(_PR, [_verdict("a", Decision.APPROVE), _verdict("b", Decision.APPROVE, pr="#30")])


def test_panel_spanning_two_heads_fails_loud() -> None:
    with pytest.raises(ValueError, match="multiple head"):
        reconcile(
            _PR,
            [_verdict("a", Decision.APPROVE), _verdict("b", Decision.APPROVE, head="deadbee")],
        )


def test_reconciliation_carries_the_head_through() -> None:
    result = reconcile(_PR, [_verdict("a", Decision.APPROVE)])
    assert result.head_sha == _HEAD


def test_confidence_out_of_range_fails_loud_at_construction() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _verdict("a", Decision.APPROVE, confidence=1.5)
