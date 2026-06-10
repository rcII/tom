"""The review-verdict contract — what an ephemeral review agent returns (R9).

R9 runs parallelizable bounded work — PR reviews — on one-shot agents: each is
spawned for a single (PR, lens), returns a structured verdict, and dies. N of them
run concurrently and their verdicts are reconciled into one panel result. These
are the shapes that flow; the agent that produces a verdict and the transport that
carries it are layered on top.

A verdict is a *structured* judgement, not prose — the same discipline the rest of
the comms system uses (a resolution is data, not an imperative). The reconciler
reads the structure (decisions + finding severities), never free text, so a
reviewer can't smuggle an outcome past the panel logic in a sentence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    """A single reviewer's verdict on a PR."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request-changes"
    COMMENT = "comment"


class Severity(StrEnum):
    """How much a finding matters. ``BLOCKING`` is the quality-pillar bar: it must
    not merge until folded, whatever decision the reviewer attached."""

    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a reviewer found, located and classified."""

    severity: Severity
    file: str
    claim: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """What one ephemeral agent is asked to review: a PR, through one lens, pinned
    to a head SHA so the verdict is verify-at-head and never a moving target."""

    pr: str
    lens: str
    head_sha: str


@dataclass(frozen=True, slots=True)
class ReviewVerdict:
    """One agent's structured verdict on one (PR, lens), at a head SHA.

    ``confidence`` is the agent's own 0..1 self-rating; the reconciler uses it to
    surface low-confidence verdicts, never to silently drop a finding.
    """

    pr: str
    lens: str
    head_sha: str
    decision: Decision
    findings: tuple[Finding, ...] = ()
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in 0..1, got {self.confidence}")
