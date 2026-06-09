"""Reconciling a panel of review verdicts into one result.

The load-bearing rule is the quality pillar's: a **blocking** finding holds the
merge no matter what decision the reviewer who found it attached. A reviewer can
cite a real blocker and still stamp APPROVE or COMMENT (under-classified); the
reconciler re-classes the panel to REQUEST_CHANGES on the *finding severity*, not
the reviewer's headline, and flags that it did so (``escalated``) so the
escalation is visible rather than buried. Low-confidence verdicts are surfaced,
never silently dropped.

The reconciler reads structure only — decisions and severities — so an outcome
can't be argued past it in prose, the same data-not-narrative discipline the rest
of the comms system holds.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tom.schemas.review import Decision, Finding, ReviewVerdict, Severity

#: Verdicts at or below this self-rated confidence are surfaced for a second look.
_DEFAULT_LOW_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class ReviewReconciliation:
    """The panel's reconciled outcome for one PR at one head.

    ``escalated`` is True when ``overall`` is REQUEST_CHANGES purely because of a
    blocking finding — no reviewer's own headline said REQUEST_CHANGES — i.e. the
    panel caught an under-classified blocker.
    """

    pr: str
    head_sha: str
    overall: Decision
    verdicts: tuple[ReviewVerdict, ...]
    blocking_findings: tuple[Finding, ...]
    escalated: bool
    low_confidence: tuple[ReviewVerdict, ...]


def reconcile(
    pr: str,
    verdicts: Iterable[ReviewVerdict],
    *,
    low_confidence_threshold: float = _DEFAULT_LOW_CONFIDENCE,
) -> ReviewReconciliation:
    """Fold a panel's verdicts into one result for ``pr``.

    Fails loud on an empty panel, a verdict for a different PR, or verdicts spread
    across different head SHAs — each would make the reconciliation meaningless or
    a moving target, so none is papered over.
    """
    panel = tuple(verdicts)
    if not panel:
        raise ValueError("cannot reconcile an empty panel")

    mismatched = {v.pr for v in panel if v.pr != pr}
    if mismatched:
        raise ValueError(f"panel for {pr} contains verdicts for {sorted(mismatched)}")

    heads = {v.head_sha for v in panel}
    if len(heads) != 1:
        raise ValueError(f"panel spans multiple head SHAs: {sorted(heads)}")
    head_sha = next(iter(heads))

    blocking = tuple(
        finding
        for verdict in panel
        for finding in verdict.findings
        if finding.severity is Severity.BLOCKING
    )
    any_request_changes = any(v.decision is Decision.REQUEST_CHANGES for v in panel)

    if any_request_changes or blocking:
        overall = Decision.REQUEST_CHANGES
    elif all(v.decision is Decision.APPROVE for v in panel):
        overall = Decision.APPROVE
    else:
        overall = Decision.COMMENT

    # Escalated when the only reason for REQUEST_CHANGES is a blocking finding that
    # no reviewer's headline flagged — the under-classified-blocker catch.
    escalated = overall is Decision.REQUEST_CHANGES and not any_request_changes

    low_confidence = tuple(v for v in panel if v.confidence <= low_confidence_threshold)

    return ReviewReconciliation(
        pr=pr,
        head_sha=head_sha,
        overall=overall,
        verdicts=panel,
        blocking_findings=blocking,
        escalated=escalated,
        low_confidence=low_confidence,
    )
