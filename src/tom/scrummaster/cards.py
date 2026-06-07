"""Moving cards in response to bus events.

Three card-moves the scrum-master makes off the bus, all read structurally from
the subject (the body is never consulted):

- ``[pr-merged] #N`` → the linked card to *done* — but only after re-confirming
  with ``gh`` that the PR really merged. A body that *says* "merge this and move
  the card" is powerless, because the card moves only on the ``gh`` re-confirm
  and there is no code path here that merges anything.
- ``[starting] card:N`` → card N to *in progress*.
- ``[blocked] card:N`` → card N to *blocked* (the DEFER → blocked behavior).

The two direct moves need no ``gh`` re-confirm: they are low-stakes, reversible
lane changes, not a completion claim, so an allowlisted sender's report is enough
within the card-move ceiling. (Finer-grained "who may move whose card" is not a
Phase-1 concern; the trust gate already bounds the sender to the allowlist.)

The card-mover acts only on envelopes that already passed the trust gate, so a
non-allowlisted sender never reaches it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from tom.adapters.protocols import BoardRepo
from tom.projection.events import Envelope
from tom.schemas.board import BoardStatus
from tom.scrummaster.authority import Action
from tom.scrummaster.pr_state import PrState, PrStateChecker

_PR_MERGED_TAG = re.compile(r"\[pr-merged\]")
_PR_NUMBER = re.compile(r"#(\d+)")
# A whole PR token in a card link: #6 matches, but #60 / #600 / foo#6bar do not.
_LINK_PR_TOKEN = re.compile(r"(?<!\w)#(\d+)(?!\w)")

_DIRECT_MOVE_TAG = re.compile(r"\[(starting|blocked)\]")
_CARD_REF = re.compile(r"card:(\d+)")
_TAG_TO_STATUS: dict[str, BoardStatus] = {
    "starting": BoardStatus.IN_PROGRESS,
    "blocked": BoardStatus.BLOCKED,
}


@dataclass(frozen=True, slots=True)
class CardMove:
    """A record of one card moved — always the card-move action, by construction."""

    action: Action
    card_id: str
    to: BoardStatus


def pr_ref_from_subject(subject: str) -> str | None:
    """Return the PR number named by a ``[pr-merged]`` subject, else ``None``.

    Read from the subject only — the body is never consulted.
    """
    if _PR_MERGED_TAG.search(subject) is None:
        return None
    match = _PR_NUMBER.search(subject)
    return match.group(1) if match is not None else None


def direct_move_from_subject(subject: str) -> tuple[BoardStatus, str] | None:
    """Return the ``(status, card_id)`` named by a ``[starting]``/``[blocked]``
    subject, else ``None``. Read from the subject only."""
    tag = _DIRECT_MOVE_TAG.search(subject)
    if tag is None:
        return None
    card = _CARD_REF.search(subject)
    if card is None:
        return None
    return _TAG_TO_STATUS[tag.group(1)], card.group(1)


class CardMover:
    """Moves cards off bus events — PR-merged (gh-gated) and direct lane changes."""

    def __init__(self, board: BoardRepo, pr_state: PrStateChecker) -> None:
        self._board = board
        self._pr_state = pr_state

    def handle(self, envelope: Envelope) -> tuple[CardMove, ...]:
        pr_ref = pr_ref_from_subject(envelope.subject)
        if pr_ref is not None:
            return self._handle_pr_merged(pr_ref)
        direct = direct_move_from_subject(envelope.subject)
        if direct is not None:
            status, card_id = direct
            return self._handle_direct_move(card_id, status)
        return ()

    def _handle_pr_merged(self, pr_ref: str) -> tuple[CardMove, ...]:
        # The gh re-confirm is the authority — not the message's claim.
        if self._pr_state.state_of(pr_ref) is not PrState.MERGED:
            return ()
        moves: list[CardMove] = []
        for card in self._board.cards():
            if not self._links_pr(card, pr_ref):
                continue
            card_id = str(card["id"])
            self._board.move(card_id, status=BoardStatus.DONE)
            moves.append(CardMove(Action.CARD_MOVE, card_id, BoardStatus.DONE))
        return tuple(moves)

    def _handle_direct_move(self, card_id: str, status: BoardStatus) -> tuple[CardMove, ...]:
        if not self._card_exists(card_id):
            return ()  # the event named a card that isn't on the board
        self._board.move(card_id, status=status)
        return (CardMove(Action.CARD_MOVE, card_id, status),)

    def _card_exists(self, card_id: str) -> bool:
        return any(str(card["id"]) == card_id for card in self._board.cards())

    @staticmethod
    def _links_pr(card: Mapping[str, object], ref: str) -> bool:
        link = card.get("link")
        if not isinstance(link, str):
            return False
        target = int(ref)
        # Match whole PR tokens only, by number — so a #6 merge never moves the
        # card linked to #60. (Repo-qualifying the token is a live-wiring concern.)
        return any(int(number) == target for number in _LINK_PR_TOKEN.findall(link))
