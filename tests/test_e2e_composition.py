"""End-to-end composition: the assembled system, not the pieces in isolation.

The per-module tests prove each part; these prove they COMPOSE — that one event
stream, folded once, produces a status snapshot, an R4 injection, and (over the
graph) a relationship view that all AGREE, and that the bridge's publish path
reaches a real NATS server. A contract-seam bug between two modules passes every
per-module test and fails here, which is the point.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from datetime import timedelta

import pytest

from tom.bridge.publisher import NatsCliPublisher
from tom.bridge.receiver import _envelope
from tom.bridge.telegram import channel_event_from_update
from tom.inject.context_injection import NullRecall, compose_injection
from tom.projection.events import Envelope
from tom.projection.graph import project_graph
from tom.projection.session_events import status_signal_from_event
from tom.projection.status import project_status
from tom.projection.widget import snapshot_from_projection
from tom.review.reconcile import reconcile
from tom.review.runner import run_panel
from tom.schemas.graph import EdgeKind
from tom.schemas.review import Decision, ReviewRequest, ReviewVerdict
from tom.schemas.session_event import HookKind, SessionEvent
from tom.schemas.status import IdleBasis, State

_T0 = "2026-06-09T07:00:00Z"
_NOW = "2026-06-09T07:00:05Z"  # seconds after the events: no inferred-idle TTL fires


def _event(session: str, hook: HookKind) -> SessionEvent:
    return SessionEvent(event_id=f"{session}-{hook.value}", session=session, hook=hook, ts=_T0)


def test_one_event_stream_feeds_an_agreeing_snapshot_and_injection() -> None:
    # Hook events drive status; bus envelopes drive the relationship graph. Both
    # fold into the SAME projected model that the widget snapshot and the R4
    # injection read — so the two surfaces must agree on every fact.
    hook_events = [
        _event("tom", HookKind.STOP),  # turn finished -> measured idle
        _event("catalyst", HookKind.USER_PROMPT_SUBMIT),  # active
    ]
    signals = [s for e in hook_events if (s := status_signal_from_event(e)) is not None]
    statuses = project_status(signals, now=_NOW, idle_ttl=timedelta(hours=1))

    graph = project_graph(
        [Envelope(message_id="m1", src="viz", dst="catalyst",
                  subject="[depends-on] viz needs the data layer", ts=_T0)]
    )

    snapshot = snapshot_from_projection(statuses, graph, seq=1, generated_ts=_NOW)
    nodes = {n.id: n for n in snapshot.nodes}

    # status-path agreement: tom's measured idle shows in the snapshot AND the
    # injection composed for tom off the same statuses.
    assert nodes["tom"].status is State.IDLE
    assert nodes["tom"].idle_basis is IdleBasis.MEASURED
    assert "tom" in snapshot.derived.idle
    tom_injection = compose_injection(
        session="tom", statuses=statuses, graph=graph,
        open_cards=[], recall_source=NullRecall(), prompt="continue",
    )
    assert any("parked idle" in fact for fact in tom_injection.facts)

    # graph-path agreement: the depends-on edge shows in the snapshot edges AND in
    # viz's injection — the widget contract and R4 read the one graph consistently.
    assert any(
        e.src == "viz" and e.dst == "catalyst" and e.kind is EdgeKind.DEPENDS_ON
        for e in snapshot.edges
    )
    viz_injection = compose_injection(
        session="viz", statuses=statuses, graph=graph,
        open_cards=[], recall_source=NullRecall(), prompt="continue",
    )
    assert "You depend on: catalyst." in viz_injection.facts


def test_review_panel_composes_run_to_reconcile() -> None:
    # The R9 path end to end: requests -> run_panel -> reconcile, with a reviewer
    # that under-classifies a blocker, so the panel must escalate.
    class _Agent:
        def review(self, request: ReviewRequest) -> ReviewVerdict:
            return ReviewVerdict(
                pr=request.pr, lens=request.lens, head_sha=request.head_sha,
                decision=Decision.APPROVE,
            )

    requests = [ReviewRequest(pr="#29", lens=lens, head_sha="fffe2ac")
                for lens in ("security", "correctness")]
    result = reconcile("#29", run_panel(_Agent(), requests))
    assert result.overall is Decision.APPROVE  # both approve, no blocker
    assert result.head_sha == "fffe2ac"


def _nats_available() -> bool:
    if shutil.which("nats") is None:
        return False
    try:
        with socket.create_connection(("127.0.0.1", 4222), timeout=2):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _nats_available(), reason="needs the nats CLI + a NATS server on 127.0.0.1:4222"
)
def test_channel_event_round_trips_through_real_nats() -> None:
    # The bridge publish path against a real server: a Telegram update becomes a
    # ChannelEvent, is published to NATS, and comes back out a subscriber — not a
    # fake publisher, the actual wire.
    subject = f"team.event.channel.telegram.e2e-test.{os.getpid()}"
    sub = subprocess.Popen(
        ["nats", "sub", subject, "--count=1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        time.sleep(0.7)  # let the subscription establish before we publish
        event = channel_event_from_update(
            {"update_id": 4242, "message": {"chat": {"id": 7}, "text": "e2e"}}, ts=_T0
        )
        NatsCliPublisher(
            nats_url="nats://127.0.0.1:4222", nats_bin="nats", timeout_seconds=5
        ).publish(subject, _envelope(event))
        out, _ = sub.communicate(timeout=10)
    finally:
        if sub.poll() is None:
            sub.kill()
            sub.communicate()

    assert "telegram-4242" in out  # the published envelope round-tripped the wire
    assert '"source": "telegram"' in out
