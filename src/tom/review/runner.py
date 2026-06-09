"""The spawn/collect seam for the review panel.

:class:`ReviewAgent` is the contract a one-shot reviewer satisfies: take a
request, return a verdict. The real one is an ephemeral SDK agent (``query()``
one-shot, spawned per request, run concurrently, dead after); a recording fake
stands in for tests. :func:`run_panel` drives a set of requests through an agent
and collects the verdicts — the unit the reconciler folds.

A request that raises is captured, not swallowed: it becomes a failed verdict
(REQUEST_CHANGES, a blocking finding naming the failure) so a crashed reviewer
holds the merge rather than vanishing from the panel and letting it look cleaner
than it is — a silent missing reviewer is the failure mode this guards against.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from tom.schemas.review import (
    Decision,
    Finding,
    ReviewRequest,
    ReviewVerdict,
    Severity,
)


@runtime_checkable
class ReviewAgent(Protocol):
    """A one-shot reviewer: one request in, one verdict out."""

    def review(self, request: ReviewRequest) -> ReviewVerdict: ...


def run_panel(
    agent: ReviewAgent, requests: Iterable[ReviewRequest]
) -> tuple[ReviewVerdict, ...]:
    """Run each request through ``agent`` and collect the verdicts.

    A request whose review raises becomes a failed verdict rather than a gap, so
    the panel never silently shrinks. The real runner spawns these concurrently;
    the collection contract is the same either way.
    """
    return tuple(_review_or_fail(agent, request) for request in requests)


def _review_or_fail(agent: ReviewAgent, request: ReviewRequest) -> ReviewVerdict:
    try:
        return agent.review(request)
    except Exception as exc:
        # A reviewer can fail any number of ways (model timeout, malformed output,
        # transport). Capture every one as a holding verdict — a crashed reviewer
        # must hold the panel, never vanish from it and make the PR look cleaner.
        return ReviewVerdict(
            pr=request.pr,
            lens=request.lens,
            head_sha=request.head_sha,
            decision=Decision.REQUEST_CHANGES,
            findings=(
                Finding(
                    severity=Severity.BLOCKING,
                    file="<review-agent>",
                    claim=f"reviewer for lens {request.lens!r} failed: {exc}",
                ),
            ),
            confidence=0.0,
        )
