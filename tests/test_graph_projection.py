"""The relationship graph is derived from the bus, deterministically.

Covers the graph half of the shared-context model: edges come from envelopes
and dispatches, kinds come from the subject (never the body), and replaying the
same log in any order rebuilds an identical graph.
"""

from __future__ import annotations

import pytest

from tom.projection.events import Dispatch, Envelope
from tom.projection.graph import GraphProjection, project_graph
from tom.schemas.graph import EdgeKind, InteractionEdge, Node, NodeKind


def _envelope(
    message_id: str,
    src: str,
    dst: str,
    subject: str,
    ts: str,
    body: dict[str, object] | None = None,
) -> Envelope:
    return Envelope(
        message_id=message_id,
        src=src,
        dst=dst,
        subject=subject,
        ts=ts,
        body=body if body is not None else {},
    )


def _sample_events() -> list[Envelope | Dispatch]:
    return [
        _envelope("m1", "tom", "tpm", "[review-of] PR #1", "2026-06-07T01:00:00-05:00"),
        _envelope("m2", "catalyst", "tom", "just a heads up", "2026-06-07T01:05:00-05:00"),
        Dispatch(
            subagent_id="20260607T010600_tom_a1b2",
            requesting_session="tom",
            ts="2026-06-07T01:06:00-05:00",
        ),
    ]


def test_graph_is_derived_from_envelopes_and_dispatches() -> None:
    proj = project_graph(_sample_events())

    assert proj.nodes == (
        Node(id="20260607T010600_tom_a1b2", kind=NodeKind.SUBAGENT),
        Node(id="catalyst", kind=NodeKind.SESSION),
        Node(id="tom", kind=NodeKind.SESSION),
        Node(id="tpm", kind=NodeKind.SESSION),
    )
    assert proj.edges == (
        InteractionEdge(
            src="tom", dst="tpm", kind=EdgeKind.REVIEW_OF,
            ts="2026-06-07T01:00:00-05:00", ref="m1",
        ),
        InteractionEdge(
            src="catalyst", dst="tom", kind=EdgeKind.MESSAGE,
            ts="2026-06-07T01:05:00-05:00", ref="m2",
        ),
        InteractionEdge(
            src="tom", dst="20260607T010600_tom_a1b2", kind=EdgeKind.HANDS_OFF,
            ts="2026-06-07T01:06:00-05:00", ref="20260607T010600_tom_a1b2",
        ),
    )


def test_edge_kind_comes_from_subject_not_body() -> None:
    # The subject says blocks; the body lies and says message. The subject wins.
    events = [
        _envelope(
            "m1", "catalyst", "tom",
            "[blocks] waiting on the kernel port",
            "2026-06-07T01:00:00-05:00",
            body={"kind": "message"},
        ),
        # And the reverse: a plain subject with a body claiming a kind.
        _envelope(
            "m2", "tom", "catalyst",
            "plain subject",
            "2026-06-07T01:01:00-05:00",
            body={"kind": "blocks"},
        ),
    ]
    proj = project_graph(events)
    by_ref = {edge.ref: edge.kind for edge in proj.edges}
    assert by_ref["m1"] == EdgeKind.BLOCKS
    assert by_ref["m2"] == EdgeKind.MESSAGE


def test_rebuild_is_order_independent() -> None:
    events = _sample_events()
    forward = project_graph(events)
    reversed_proj = project_graph(list(reversed(events)))
    scrambled = project_graph([events[2], events[0], events[1]])

    assert forward == reversed_proj == scrambled
    # Re-running the same input is identical too — the rebuild is the only path.
    assert project_graph(events) == forward


def test_replay_of_a_redelivered_message_is_idempotent() -> None:
    one = _envelope("m1", "tom", "tpm", "[review-of] PR #1", "2026-06-07T01:00:00-05:00")
    proj = project_graph([one, one, one])
    assert len(proj.edges) == 1


def test_since_window_drops_older_edges() -> None:
    events = _sample_events()
    proj = project_graph(events, since="2026-06-07T01:05:00-05:00")
    # The 01:00 review-of edge is before the cutoff and dropped; its dst node
    # (tpm) goes with it.
    refs = {edge.ref for edge in proj.edges}
    assert refs == {"m2", "20260607T010600_tom_a1b2"}
    assert all(node.id != "tpm" for node in proj.nodes)


def test_since_boundary_is_inclusive() -> None:
    events = _sample_events()
    proj = project_graph(events, since="2026-06-07T01:00:00-05:00")
    assert any(edge.ref == "m1" for edge in proj.edges)


def test_session_identity_dominates_subagent_regardless_of_order() -> None:
    # A pathological id that shows up both as a dispatched sub-agent and as a
    # message sender. The session identity must win either way the events fall.
    shared = "shared-id"
    disp = Dispatch(subagent_id=shared, requesting_session="tom", ts="2026-06-07T01:00:00-05:00")
    env = _envelope("m1", shared, "tpm", "hi", "2026-06-07T01:01:00-05:00")

    forward = project_graph([disp, env])
    backward = project_graph([env, disp])
    node = {n.id: n for n in forward.nodes}[shared]
    assert node.kind == NodeKind.SESSION
    assert forward == backward


def test_empty_stream_is_an_empty_graph() -> None:
    assert project_graph([]) == GraphProjection(nodes=(), edges=())


def test_naive_timestamp_fails_loud() -> None:
    bad = _envelope("m1", "tom", "tpm", "hi", "2026-06-07T01:00:00")
    with pytest.raises(ValueError, match="no timezone offset"):
        project_graph([bad])


def test_unparseable_timestamp_fails_loud() -> None:
    bad = _envelope("m1", "tom", "tpm", "hi", "not-a-timestamp")
    with pytest.raises(ValueError, match="unparseable timestamp"):
        project_graph([bad])


def test_unparseable_window_cutoff_fails_loud() -> None:
    with pytest.raises(ValueError, match="window cutoff"):
        project_graph(_sample_events(), since="garbage")
