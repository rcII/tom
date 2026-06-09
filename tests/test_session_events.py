"""Hook events fold into the status projection the same model already uses."""

from __future__ import annotations

from datetime import timedelta

from tom.projection.events import SignalKind
from tom.projection.session_events import status_signal_from_event
from tom.projection.status import project_status
from tom.schemas.session_event import EventOrigin, HookKind, SessionEvent
from tom.schemas.status import IdleBasis, State

TS = "2026-06-09T01:00:00-05:00"


def _event(hook: HookKind, *, session: str = "catalyst", **payload: object) -> SessionEvent:
    return SessionEvent(event_id="e1", session=session, hook=hook, ts=TS, payload=payload)


def test_stop_is_a_measured_idle() -> None:
    signal = status_signal_from_event(_event(HookKind.STOP))
    assert signal is not None
    assert signal.kind is SignalKind.IDLE
    # Folded through the projection, a Stop reads as a MEASURED idle, not inferred.
    (status,) = project_status([signal], now=TS, idle_ttl=timedelta(minutes=10))
    assert status.state is State.IDLE
    assert status.idle_basis is IdleBasis.MEASURED


def test_permission_request_is_blocked() -> None:
    signal = status_signal_from_event(_event(HookKind.PERMISSION_REQUEST))
    assert signal is not None and signal.kind is SignalKind.BLOCKED
    (status,) = project_status([signal], now=TS, idle_ttl=timedelta(minutes=10))
    assert status.state is State.BLOCKED


def test_activity_hooks_are_alive() -> None:
    for hook in (HookKind.PRE_TOOL_USE, HookKind.POST_TOOL_USE, HookKind.NOTIFICATION):
        signal = status_signal_from_event(_event(hook))
        assert signal is not None and signal.kind is SignalKind.HEARTBEAT


def test_started_hooks_set_active_with_task() -> None:
    signal = status_signal_from_event(
        _event(HookKind.USER_PROMPT_SUBMIT, task="wire the event contract")
    )
    assert signal is not None
    assert signal.kind is SignalKind.STARTED
    assert signal.task == "wire the event contract"


def test_session_end_yields_no_status_signal() -> None:
    assert status_signal_from_event(_event(HookKind.SESSION_END)) is None


def test_kind_comes_from_the_hook_not_the_payload() -> None:
    # A payload that claims a different kind doesn't change the derivation.
    event = _event(HookKind.STOP, kind="started", task="x")
    signal = status_signal_from_event(event)
    assert signal is not None and signal.kind is SignalKind.IDLE


def test_event_defaults_to_first_party_origin() -> None:
    assert _event(HookKind.STOP).origin is EventOrigin.FIRST_PARTY
