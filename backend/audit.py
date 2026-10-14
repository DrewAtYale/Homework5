"""Append-only audit trail: output/audit_trail.json.

The file is a JSON array. Each agent loop step adds one entry. Entries are only ever appended:
nothing here deletes, rewrites or trims earlier runs. If the file is unreadable it's kept as a
backup and a new array is started, so one bad write never loses history.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from config import AUDIT_PATH, AUDIT_TRUNCATE
from models import AuditStep

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def truncate(value: object, limit: int = AUDIT_TRUNCATE) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def append(step: AuditStep) -> None:
    """Append one step. Never raises: auditing must not crash a ticket run."""
    try:
        with _lock:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            entries: list = []
            if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size:
                try:
                    entries = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
                    if not isinstance(entries, list):
                        raise ValueError("audit trail is not a JSON array")
                except ValueError:
                    backup = AUDIT_PATH.with_name(f"audit_trail.corrupt-{datetime.now():%Y%m%d%H%M%S}.json")
                    AUDIT_PATH.replace(backup)
                    entries = []
            entries.append(step.model_dump(mode="json"))
            AUDIT_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def read_all() -> list[dict]:
    """Every audit entry, oldest first. Shares the writer's lock so a half-written file is never read."""
    with _lock:
        if not AUDIT_PATH.exists() or not AUDIT_PATH.stat().st_size:
            return []
        try:
            entries = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
    return entries if isinstance(entries, list) else []
