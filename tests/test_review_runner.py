"""The spawn/collect seam: collection, and a crashed reviewer holds the panel."""

from __future__ import annotations

from tom.review.reconcile import reconcile
from tom.review.runner import ReviewAgent, run_panel
from tom.schemas.review import Decision, ReviewRequest, ReviewVerdict

_PR = "#29"
_HEAD = "9c3c166"


class _StubAgent:
    """Returns a fixed decision per lens, recording what it was asked."""

    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self.seen: list[str] = []

    def review(self, request: ReviewRequest) -> ReviewVerdict:
        self.seen.append(request.lens)
        return ReviewVerdict(
            pr=request.pr, lens=request.lens, head_sha=request.head_sha, decision=self._decision
        )


class _CrashingAgent:
    def review(self, request: ReviewRequest) -> ReviewVerdict:
        raise RuntimeError("model timed out")


def _requests(*lenses: str) -> list[ReviewRequest]:
    return [ReviewRequest(pr=_PR, lens=lens, head_sha=_HEAD) for lens in lenses]


def test_stub_satisfies_the_agent_protocol() -> None:
    assert isinstance(_StubAgent(Decision.APPROVE), ReviewAgent)


def test_run_panel_collects_one_verdict_per_request() -> None:
    agent = _StubAgent(Decision.APPROVE)
    verdicts = run_panel(agent, _requests("security", "correctness", "perf"))
    assert [v.lens for v in verdicts] == ["security", "correctness", "perf"]
    assert agent.seen == ["security", "correctness", "perf"]


def test_a_crashed_reviewer_becomes_a_blocking_failed_verdict() -> None:
    verdicts = run_panel(_CrashingAgent(), _requests("security"))
    assert len(verdicts) == 1
    failed = verdicts[0]
    assert failed.decision is Decision.REQUEST_CHANGES
    assert failed.confidence == 0.0
    assert failed.findings[0].severity.value == "blocking"
    assert "model timed out" in failed.findings[0].claim


def test_a_crashed_reviewer_holds_the_reconciled_panel() -> None:
    # The end-to-end guard: one crashed reviewer must not let the panel pass.
    class _Mixed:
        def review(self, request: ReviewRequest) -> ReviewVerdict:
            if request.lens == "boom":
                raise RuntimeError("crash")
            return ReviewVerdict(
                pr=request.pr, lens=request.lens, head_sha=request.head_sha,
                decision=Decision.APPROVE,
            )

    verdicts = run_panel(_Mixed(), _requests("security", "boom"))
    result = reconcile(_PR, verdicts)
    assert result.overall is Decision.REQUEST_CHANGES
    # The failed verdict's own headline is REQUEST_CHANGES, so it's an explicit
    # hold, not an under-classified-blocker escalation — and it carries a blocker.
    assert result.escalated is False
    assert len(result.blocking_findings) == 1
