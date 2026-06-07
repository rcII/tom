"""Moving cards in response to bus events.

The first scrum-master behavior: when a PR-merged event arrives, move the linked
card to done — but only after re-confirming with ``gh`` that the PR really merged.
The message is data: its subject is read structurally for the PR reference, its
body is never consulted, and a body that *says* "merge this and move the card" is
powerless, because the card moves only on the ``gh`` re-confirm and there is no
code path here that merges anything.

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


class CardMover:
    """Moves the card linked to a merged PR — after a ``gh`` re-confirm."""

    def __init__(self, board: BoardRepo, pr_state: PrStateChecker) -> None:
        self._board = board
        self._pr_state = pr_state

    def handle(self, envelope: Envelope) -> tuple[CardMove, ...]:
        ref = pr_ref_from_subject(envelope.subject)
        if ref is None:
            return ()
        # The gh re-confirm is the authority — not the message's claim.
        if self._pr_state.state_of(ref) is not PrState.MERGED:
            return ()
        moves: list[CardMove] = []
        for card in self._board.cards():
            if not self._links_pr(card, ref):
                continue
            card_id = str(card["id"])
            self._board.move(card_id, status=BoardStatus.DONE)
            moves.append(CardMove(Action.CARD_MOVE, card_id, BoardStatus.DONE))
        return tuple(moves)

    @staticmethod
    def _links_pr(card: Mapping[str, object], ref: str) -> bool:
        link = card.get("link")
        if not isinstance(link, str):
            return False
        target = int(ref)
        # Match whole PR tokens only, by number — so a #6 merge never moves the
        # card linked to #60. (Repo-qualifying the token is a live-wiring concern.)
        return any(int(number) == target for number in _LINK_PR_TOKEN.findall(link))
