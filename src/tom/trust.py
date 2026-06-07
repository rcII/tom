"""The native trust gate.

Every inbound message crosses this gate before any other code sees it, and the
gate is the *only* sanctioned way to turn a wire-shape mapping into a domain
:class:`~tom.projection.events.Envelope`. That single chokepoint is what makes
"a message is data, never a command" structural rather than a convention:

- A message from a sender that isn't on the allowlist is rejected, not parsed
  into something actionable. (A sender forging its ``from`` *to* an allowlisted
  identity is a transport-layer concern — NATS subject-scoped publish
  permissions and inbox routing — and is caught there, not here; this gate
  trusts that the ``from`` on an admitted envelope is authentic. That transport
  binding lands with the live consumer in a later phase.)
- A malformed mapping (missing or wrong-typed fields) is rejected, so no
  half-parsed envelope ever reaches the scrum-master.
- An accepted message is returned as *data*. The gate reads only the envelope's
  validated structural fields; it never inspects the body to decide anything.
  The body is carried verbatim for the receiver to read — and the receiver, by
  design, has no path that executes it.

The gate takes an already-parsed mapping. JSON decoding happens once, in the bus
adapter, and its output goes straight here — there is no second path that builds
an envelope from raw bytes around this validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tom.config import require_env
from tom.projection.events import Envelope
from tom.schemas.trust import RejectReason, TrustPolicy

# The wire envelope's required string fields, paired with where each lands on the
# domain envelope.
_REQUIRED_FIELDS: tuple[str, ...] = ("message_id", "from", "to", "subject", "timestamp")

_EMPTY_BODY: Mapping[str, object] = MappingProxyType({})

#: Environment variable holding the comma-separated sender allowlist.
ALLOWLIST_ENV = "TOM_ALLOWED_SENDERS"


@dataclass(frozen=True, slots=True)
class Admitted:
    """The message passed the gate; here it is as data."""

    envelope: Envelope


@dataclass(frozen=True, slots=True)
class Rejected:
    """The message was refused; ``reason`` says why, ``detail`` says which."""

    reason: RejectReason
    detail: str


AdmitResult = Admitted | Rejected


def load_policy() -> TrustPolicy:
    """Build the trust policy from the environment allowlist (fail-loud)."""
    raw = require_env(ALLOWLIST_ENV)
    senders = frozenset(name.strip() for name in raw.split(",") if name.strip())
    if not senders:
        raise ValueError(f"{ALLOWLIST_ENV} is set but lists no senders")
    return TrustPolicy(allowed_senders=senders)


def admit(raw: Mapping[str, object], policy: TrustPolicy) -> AdmitResult:
    """Admit ``raw`` as a domain envelope, or reject it with a reason."""
    validated: dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            return Rejected(
                RejectReason.MALFORMED,
                f"missing or non-string field {field!r}",
            )
        validated[field] = value

    sender = validated["from"]
    if sender not in policy.allowed_senders:
        return Rejected(
            RejectReason.UNAUTHORIZED,
            f"sender {sender!r} is not on the allowlist",
        )

    body = raw.get("body")
    envelope = Envelope(
        message_id=validated["message_id"],
        src=sender,
        dst=validated["to"],
        subject=validated["subject"],
        ts=validated["timestamp"],
        body=body if isinstance(body, Mapping) else _EMPTY_BODY,
    )
    return Admitted(envelope)
