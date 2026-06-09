"""Folding hook events into the status projection.

The hook event stream is a richer source for the same projection the bus already
feeds. Each :class:`~tom.schemas.session_event.SessionEvent` maps to a status
signal the existing projector understands, so the live console and the status
widget read off the model that's already built — no second computation.

The mapping is structural (the hook kind decides the signal, never the payload's
free text). Two of these matter most:

- ``Stop`` fires when a session finishes its turn, so it is a *measured* idle —
  the session told us it's done, not an inferred "we haven't heard from it." That
  is the measured-idle signal the wake relay could only infer from a quiet pane.
- ``PermissionRequest`` means the session is waiting on a human decision, so it
  reads as *blocked* — and a decision card is raised so the wait is visible
  rather than a silent block.
"""

from __future__ import annotations

from tom.projection.events import SignalKind, StatusSignal
from tom.schemas.session_event import HookKind, SessionEvent

# A hook that carries no status meaning (a SessionEnd retires a node, which is a
# graph concern, not a status one) is absent and yields no signal.
_HOOK_TO_SIGNAL: dict[HookKind, SignalKind] = {
    HookKind.SESSION_START: SignalKind.STARTED,
    HookKind.USER_PROMPT_SUBMIT: SignalKind.STARTED,
    HookKind.PRE_TOOL_USE: SignalKind.HEARTBEAT,
    HookKind.POST_TOOL_USE: SignalKind.HEARTBEAT,
    HookKind.NOTIFICATION: SignalKind.HEARTBEAT,
    HookKind.STOP: SignalKind.IDLE,  # turn finished → measured idle
    HookKind.PERMISSION_REQUEST: SignalKind.BLOCKED,  # waiting on a human
}


def status_signal_from_event(event: SessionEvent) -> StatusSignal | None:
    """Map a hook event to a status signal, or ``None`` if it carries no status.

    Optional ``task`` / ``pr`` / ``stage`` are carried through from the payload
    when the producer included them, so a session's current work shows up on the
    status surface; they are read only when present and well-typed.
    """
    kind = _HOOK_TO_SIGNAL.get(event.hook)
    if kind is None:
        return None
    return StatusSignal(
        session=event.session,
        ts=event.ts,
        kind=kind,
        task=_optional_str(event, "task"),
        pr=_optional_str(event, "pr"),
        stage=_optional_str(event, "stage"),
    )


def _optional_str(event: SessionEvent, key: str) -> str | None:
    value = event.payload.get(key)
    return value if isinstance(value, str) else None
