"""The per-session wake watermark, persisted across restarts.

Each session has a watermark — the timestamp up to which its inbox has been
accounted for. New work is what arrived after it; a wake advances it to now. It's
persisted to a small JSON file so a restart doesn't reset it and replay the whole
backlog (or reset the debounce). A session we've never seen is seeded to the
relay's start time, so the existing backlog never reads as new.
"""

from __future__ import annotations

import json
from pathlib import Path


class Watermarks:
    """A JSON-backed ``session → ISO-8601 timestamp`` store."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._marks: dict[str, str] = self._load()

    def get(self, session: str) -> str | None:
        return self._marks.get(session)

    def set(self, session: str, ts: str) -> None:
        self._marks[session] = ts
        self._save()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        loaded = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{self._path} is not a JSON object of session → timestamp")
        return {str(session): str(ts) for session, ts in loaded.items()}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._marks, indent=2, sort_keys=True), encoding="utf-8")
