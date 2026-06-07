"""The scrum-master's event-processing pass.

This is the wiring that turns inbound bus messages into card moves: read the
unacked events, put each through the trust gate, hand the admitted ones to the
card-mover, and acknowledge each message once it's handled. One pass is
``run_once``; a timer (the live entrypoint, wired at deploy time) calls it on a
schedule.

Acknowledgement is the at-least-once hinge. A message is acked only *after* it is
handled, so a crash mid-handle leaves it unacked and it is redelivered on the
next pass. Card moves are idempotent (moving an already-done card to done is a
no-op-shaped write), so a redelivery is safe. A rejected message — malformed, or
from a sender off the allowlist — is acked too: the rejection is permanent, so
dropping it is correct, and the rejections are returned for the caller to log or
quarantine rather than swallowed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from tom.schemas.trust import TrustPolicy
from tom.scrummaster.cards import CardMove, CardMover
from tom.trust import Admitted, Rejected, admit


class InboundBus(Protocol):
    """What the loop needs of the bus: the unacked events, and a way to ack one."""

    def events(self) -> Iterable[Mapping[str, object]]: ...

    def ack(self, message_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """What one pass did — enough for the caller to log or quarantine on."""

    admitted: int
    rejected: tuple[Rejected, ...]
    moves: tuple[CardMove, ...]


class ScrumMasterLoop:
    """Reads inbound events and drives card moves, within the authority ceiling."""

    def __init__(self, bus: InboundBus, policy: TrustPolicy, mover: CardMover) -> None:
        self._bus = bus
        self._policy = policy
        self._mover = mover

    def run_once(self) -> ProcessingResult:
        admitted = 0
        rejected: list[Rejected] = []
        moves: list[CardMove] = []
        for raw in self._bus.events():
            result = admit(raw, self._policy)
            if isinstance(result, Admitted):
                admitted += 1
                # Handle BEFORE ack: a crash here redelivers the message.
                moves.extend(self._mover.handle(result.envelope))
            else:
                rejected.append(result)
            self._ack(raw)
        return ProcessingResult(
            admitted=admitted,
            rejected=tuple(rejected),
            moves=tuple(moves),
        )

    def _ack(self, raw: Mapping[str, object]) -> None:
        message_id = raw.get("message_id")
        if isinstance(message_id, str):
            self._bus.ack(message_id)
