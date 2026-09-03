"""
Audit trail.

Every merchant question, every explanation, every confirmation prompt and every
approved action is recorded. The trail is what lets a merchant answer "what did
this thing do on my dashboard?" afterwards.

Two rules make it safe to keep:

* Entries are **append-only in memory** for the session. Nothing is written to
  disk unless `MERCHANT_AUDIT_PATH` is set, and even then only masked text.
* Every `detail` string is passed through `merchant.masking` and then checked
  with `contains_unmasked_pii`. If PII somehow survives, the entry is replaced
  with a redaction marker rather than being written — the log must never become
  the leak.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from merchant.masking import contains_unmasked_pii, mask_text
from merchant.models import AuditEvent

MAX_EVENTS = 500
REDACTED = "[REDACTED — entry withheld because it still contained sensitive data]"


class AuditLog:
    """Session-scoped, append-only, masked."""

    def __init__(self, path: Optional[str] = None, max_events: int = MAX_EVENTS):
        self._lock = threading.RLock()
        self._events: list[AuditEvent] = []
        self._max = max_events
        self._path = path if path is not None else os.environ.get("MERCHANT_AUDIT_PATH")

    def record(self, kind: str, detail: str, outcome: str = "recorded",
               actor: str = "merchant") -> AuditEvent:
        safe = mask_text(detail or "").text
        if contains_unmasked_pii(safe):
            safe = REDACTED

        event = AuditEvent(
            event_id=uuid.uuid4().hex[:12],
            at=time.time(),
            kind=str(kind),
            detail=safe,
            outcome=str(outcome),
            actor=str(actor),
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]
        self._persist(event)
        return event

    def _persist(self, event: AuditEvent) -> None:
        """Append one JSON line, only when an explicit path is configured."""
        if not self._path:
            return
        try:
            p = Path(self._path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            # A failed audit write must never break the merchant's session.
            pass

    def events(self, limit: int = 100, kind: Optional[str] = None) -> list[AuditEvent]:
        with self._lock:
            rows = list(self._events)
        if kind:
            rows = [e for e in rows if e.kind == kind]
        return rows[-limit:][::-1]  # newest first

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


# Well-known event kinds, so the panel can filter and tests can assert on them.
KIND_QUESTION = "question"
KIND_ANSWER = "answer"
KIND_CAPTURE = "screen_capture"
KIND_PERMISSION = "permission"
KIND_CONFIRM_REQUESTED = "confirmation_requested"
KIND_CONFIRM_APPROVED = "confirmation_approved"
KIND_CONFIRM_REJECTED = "confirmation_rejected"
KIND_CONFIRM_EXPIRED = "confirmation_expired"
KIND_ACTION_BLOCKED = "action_blocked"
KIND_FALLBACK = "fallback"
KIND_ERROR = "error"
KIND_STOP = "stop_monitoring"
