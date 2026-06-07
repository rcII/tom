"""The bus, read from the Node bridge's file-mirror.

In Phase 1 the scrum-master does not own a live NATS consumer. The hardened Node
bridge already writes every inbound message durably to ``<id>-inbox/*.msg``, and
this adapter reads that mirror — so the bridge keeps owning bus reliability and
the scrum-master just consumes its durable output. The live typed consumer (with
its own reconnect and pull-stall self-heal) repoints this seam in a later phase.

This is the consume side of the :class:`~tom.adapters.protocols.BusClient` seam:
``events`` and ``ack``. The publish side lands with the scrum-master's outbound
nudge, where its shape can be designed against the existing send path.

Acknowledgement is tracked in this adapter's own durable ledger rather than by
deleting the bridge's files: the mirror is the bridge's (and possibly other
readers'), so we never mutate it. An acked message is simply skipped on the next
read, which makes redelivery of an unacked message — and a restart — both safe:
the ledger is on disk, so a restarted scrum-master resumes exactly where it left
off. Each ``*.msg`` is decoded as JSON exactly once, here; its output goes
straight to the trust gate, with no second path that builds an envelope around
that validation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from tom.config import resolve_env

#: Environment variables locating the mirror and this adapter's ack ledger.
INBOX_DIR_ENV = "TOM_INBOX_DIR"
ACK_LEDGER_ENV = "TOM_BUS_ACK_LEDGER"


class FileMirrorEventSource:
    """Reads inbound messages from the bridge's file-mirror, with a durable ack ledger."""

    def __init__(self, inbox_dir: Path, ack_ledger: Path) -> None:
        self._inbox_dir = inbox_dir
        self._ack_ledger = ack_ledger

    @classmethod
    def from_env(cls) -> FileMirrorEventSource:
        """Build from ``TOM_INBOX_DIR`` and ``TOM_BUS_ACK_LEDGER`` (fail-loud)."""
        return cls(
            inbox_dir=Path(resolve_env(f"${{{INBOX_DIR_ENV}}}")),
            ack_ledger=Path(resolve_env(f"${{{ACK_LEDGER_ENV}}}")),
        )

    def events(self) -> list[Mapping[str, object]]:
        """Every unacked message in the mirror, oldest first by filename.

        Filenames are timestamp-prefixed, so sorting them gives a stable,
        roughly-chronological order independent of directory enumeration.
        """
        acked = self._load_acked()
        events: list[Mapping[str, object]] = []
        for path in sorted(self._inbox_dir.glob("*.msg")):
            message = self._read_message(path)
            message_id = message.get("message_id")
            if isinstance(message_id, str) and message_id in acked:
                continue
            events.append(message)
        return events

    def ack(self, message_id: str) -> None:
        """Record ``message_id`` as processed; idempotent."""
        if message_id in self._load_acked():
            return
        self._ack_ledger.parent.mkdir(parents=True, exist_ok=True)
        with self._ack_ledger.open("a", encoding="utf-8") as ledger:
            ledger.write(f"{message_id}\n")

    def _load_acked(self) -> set[str]:
        if not self._ack_ledger.exists():
            return set()
        lines = self._ack_ledger.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip()}

    @staticmethod
    def _read_message(path: Path) -> Mapping[str, object]:
        """Decode one ``*.msg`` file, failing loud on anything that isn't a JSON object.

        The bridge writes these atomically, so a non-JSON or non-object file is
        genuine corruption worth surfacing rather than skipping silently.
        Quarantining a poison message belongs to the live consumer in a later
        phase; here it stops and points at the offending file.
        """
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"{path} is not a JSON object")
        return decoded
