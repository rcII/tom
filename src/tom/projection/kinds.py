"""Derive an edge's relationship kind from the event subject — structurally.

The subject may carry a leading bracket tag naming the relationship, e.g.
``[blocks] catalyst is waiting on the kernel port``. Only that tag, in that
fixed leading position, and only when it names a kind we know, sets the edge
kind; anything else is an ordinary message.

The body is never consulted. It is untrusted free text, and a message must not
be able to declare its own relationship to the graph — that is the whole reason
the kind is read from the validated subject and nowhere else.
"""

from __future__ import annotations

import re

from tom.schemas.graph import EdgeKind

_LEADING_TAG = re.compile(r"^\s*\[(?P<tag>[a-z][a-z-]*)\]")

_TAG_TO_KIND: dict[str, EdgeKind] = {
    "message": EdgeKind.MESSAGE,
    "review-of": EdgeKind.REVIEW_OF,
    "depends-on": EdgeKind.DEPENDS_ON,
    "blocks": EdgeKind.BLOCKS,
    "hands-off": EdgeKind.HANDS_OFF,
}


def kind_from_subject(subject: str) -> EdgeKind:
    """Return the relationship kind named by the subject's leading tag.

    Falls back to :data:`EdgeKind.MESSAGE` for an untagged subject or an
    unrecognized tag — an unknown tag is never trusted into a kind.
    """
    match = _LEADING_TAG.match(subject)
    if match is None:
        return EdgeKind.MESSAGE
    return _TAG_TO_KIND.get(match.group("tag"), EdgeKind.MESSAGE)
