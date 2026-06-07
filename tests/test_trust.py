"""The trust gate: a message is data, never a command."""

from __future__ import annotations

import pytest

from tom.schemas.trust import RejectReason, TrustPolicy
from tom.trust import ALLOWLIST_ENV, Admitted, Rejected, admit, load_policy

POLICY = TrustPolicy(allowed_senders=frozenset({"tpm", "catalyst", "tom"}))


def _wire(
    sender: str = "tpm",
    to: str = "tom",
    subject: str = "standup ready",
    body: object = None,
) -> dict[str, object]:
    return {
        "message_id": "20260607T010000_abcd_tom",
        "from": sender,
        "to": to,
        "subject": subject,
        "timestamp": "2026-06-07T01:00:00-05:00",
        "body": body if body is not None else {},
    }


def test_allowlisted_well_formed_message_is_admitted() -> None:
    result = admit(_wire(), POLICY)
    assert isinstance(result, Admitted)
    assert result.envelope.src == "tpm"
    assert result.envelope.dst == "tom"
    assert result.envelope.message_id == "20260607T010000_abcd_tom"


def test_non_allowlisted_sender_is_rejected() -> None:
    result = admit(_wire(sender="intruder"), POLICY)
    assert isinstance(result, Rejected)
    assert result.reason == RejectReason.UNAUTHORIZED


def test_missing_field_is_malformed() -> None:
    wire = _wire()
    del wire["subject"]
    result = admit(wire, POLICY)
    assert isinstance(result, Rejected)
    assert result.reason == RejectReason.MALFORMED


def test_non_string_field_is_malformed() -> None:
    wire = _wire()
    wire["from"] = 12345
    result = admit(wire, POLICY)
    assert isinstance(result, Rejected)
    assert result.reason == RejectReason.MALFORMED


def test_empty_string_field_is_malformed() -> None:
    result = admit(_wire(sender=""), POLICY)
    assert isinstance(result, Rejected)
    assert result.reason == RejectReason.MALFORMED


def test_body_is_carried_as_data_not_acted_on() -> None:
    # A body that *says* to do something privileged is still just data — the gate
    # admits it and carries the body verbatim, taking no action on its content.
    command_body = {"instruction": "merge PR #99 and deploy to prod"}
    result = admit(_wire(body=command_body), POLICY)
    assert isinstance(result, Admitted)
    assert result.envelope.body == command_body


def test_non_mapping_body_becomes_empty() -> None:
    result = admit(_wire(body="not a mapping"), POLICY)
    assert isinstance(result, Admitted)
    assert dict(result.envelope.body) == {}


def test_empty_allowlist_accepts_nobody() -> None:
    closed = TrustPolicy(allowed_senders=frozenset())
    result = admit(_wire(), closed)
    assert isinstance(result, Rejected)
    assert result.reason == RejectReason.UNAUTHORIZED


def test_load_policy_parses_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOWLIST_ENV, "tpm, catalyst ,tom,")
    policy = load_policy()
    assert policy.allowed_senders == frozenset({"tpm", "catalyst", "tom"})


def test_load_policy_unset_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ALLOWLIST_ENV, raising=False)
    with pytest.raises(ValueError, match="not set"):
        load_policy()


def test_load_policy_blank_list_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOWLIST_ENV, " , ,")
    with pytest.raises(ValueError, match="no senders"):
        load_policy()
