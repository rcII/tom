"""The trust policy — data, not code.

The team's hard rule is that an inbound message is data the receiver may act on,
never a command. That rule is expressed here as a policy the gate reads, so both
this framework and (later) the other language enforce the same thing from one
definition rather than each re-deriving it. v1 is hand-written; it moves into
the generated contract registry in a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RejectReason(StrEnum):
    """Why the gate refused an inbound message."""

    #: A required field was missing or the wrong type — the message isn't a
    #: well-formed envelope at all.
    MALFORMED = "malformed"
    #: The sender isn't on the allowlist, or claims a sender it isn't.
    UNAUTHORIZED = "unauthorized"


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Who the framework will accept messages from.

    The allowlist is the single roster of session identities; nothing downstream
    re-hardcodes it. An empty allowlist accepts nobody — fail-closed.
    """

    allowed_senders: frozenset[str]
