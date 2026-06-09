"""The session lifecycle event — a Claude Code hook, on the wire.

Each interactive session runs hooks that already fire today (SessionStart,
UserPromptSubmit, PreToolUse, PostToolUse, Notification, Stop, SessionEnd). This
is the shape each one takes when published to the bus: one typed event per hook
firing, carrying which session, which hook, when, and a hook-specific payload.

These events are the spine of the comms system. They feed the status and
relationship projections (a Stop is a *measured* idle, a PreToolUse is activity,
a SessionEnd retires a node), they render as the live console timeline, and a
PermissionRequest among them becomes a decision card instead of a silently
blocked pane.

They are **first-party**: they come from our own sessions' hooks, not from
another agent's mailbox. That origin is trusted by authentication of the producer,
a different path from the untrusted inter-session message that goes through the
trust gate. The two must not be conflated — a first-party event is telemetry the
producer is allowed to assert; an inter-session message is data the receiver
chooses to act on.

Hand-written for the draft; it joins the generated contract registry with the
rest once the producer side (which hook fires what payload) is pinned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class HookKind(StrEnum):
    """Which Claude Code hook fired."""

    SESSION_START = "session-start"
    USER_PROMPT_SUBMIT = "user-prompt-submit"
    PRE_TOOL_USE = "pre-tool-use"
    POST_TOOL_USE = "post-tool-use"
    NOTIFICATION = "notification"
    STOP = "stop"
    SESSION_END = "session-end"
    #: The runtime's decision-needed marker for R1b, raised when a `pre-tool-use`
    #: decision needs a human (it reads as blocked + raises a card). Not a raw
    #: 2.1.169 hook — on 2.1.169 R1b rides `pre-tool-use` permissionDecision +
    #: `notification`; this is the synthetic event the runtime emits to mark it.
    PERMISSION_REQUEST = "permission-request"


class EventOrigin(StrEnum):
    """Where an event came from. First-party events are trusted by producer auth,
    not by the inter-session trust gate."""

    FIRST_PARTY = "first-party"


_EMPTY_PAYLOAD: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One hook firing from one session.

    ``payload`` is hook-specific and kept open: the producer side pins the exact
    fields per hook. The status/graph projection reads only the structural fields
    (``session``, ``hook``, ``ts``); it never derives meaning from free-text in
    the payload, the same discipline the relationship graph uses for edge kind.
    """

    event_id: str
    session: str
    hook: HookKind
    ts: str
    origin: EventOrigin = EventOrigin.FIRST_PARTY
    payload: Mapping[str, object] = field(default=_EMPTY_PAYLOAD)
