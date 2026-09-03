"""
Privacy state and the capture permission gate.

Merchant Mode's privacy posture, in one place so it can be audited by reading
one short file:

* Capture is **opt-in per session**. Until `grant_permission()` is called, the
  pipeline cannot obtain a screenshot at all.
* Only the **active window** is captured, never the whole desktop, never other
  monitors.
* Screenshots are **never written to disk**. `PrivacyState` holds no image
  bytes; the bytes live in a local variable inside the capture call and are
  discarded when it returns.
* Text extracted from the screen is **masked before it leaves the function that
  produced it** (see `merchant.masking`).
* Inference is **local by default**. Sending screen content to a cloud model
  requires a second, separate opt-in and produces a warning.
* `stop_monitoring()` revokes everything immediately and is reachable from a
  single button in the panel.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PrivacySnapshot:
    """What the UI's privacy indicator renders. Contains no screen content."""

    capture_allowed: bool
    cloud_allowed: bool
    monitoring: bool
    granted_at: Optional[float]
    captures_this_session: int
    masked_fields_this_session: int
    screenshots_stored: int          # invariant: always 0
    last_capture_at: Optional[float]

    def status_text(self) -> str:
        if not self.capture_allowed:
            return "Privacy ON — screen access not granted"
        if not self.monitoring:
            return "Privacy ON — monitoring stopped"
        return "Privacy ON — active window only, nothing saved"


class PrivacyState:
    """Session-scoped privacy state. Thread-safe; no persistence anywhere."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capture_allowed = False
        self._cloud_allowed = False
        self._monitoring = False
        self._granted_at: Optional[float] = None
        self._captures = 0
        self._masked_fields = 0
        self._last_capture_at: Optional[float] = None

    # ── Permission ───────────────────────────────────────────────────────────

    def grant_permission(self) -> None:
        """Explicit user consent to read the active window."""
        with self._lock:
            self._capture_allowed = True
            self._monitoring = True
            self._granted_at = time.time()

    def stop_monitoring(self) -> None:
        """The panic button. Revokes capture immediately."""
        with self._lock:
            self._capture_allowed = False
            self._monitoring = False
            self._cloud_allowed = False

    def allow_cloud_inference(self, allowed: bool) -> None:
        """Second, separate opt-in for sending screen text off the machine."""
        with self._lock:
            self._cloud_allowed = bool(allowed)

    # ── Queries ──────────────────────────────────────────────────────────────

    @property
    def capture_allowed(self) -> bool:
        with self._lock:
            return self._capture_allowed and self._monitoring

    @property
    def cloud_allowed(self) -> bool:
        with self._lock:
            return self._cloud_allowed

    @property
    def monitoring(self) -> bool:
        with self._lock:
            return self._monitoring

    def note_capture(self, masked_fields: int = 0) -> None:
        with self._lock:
            self._captures += 1
            self._masked_fields += max(0, masked_fields)
            self._last_capture_at = time.time()

    def snapshot(self) -> PrivacySnapshot:
        with self._lock:
            return PrivacySnapshot(
                capture_allowed=self._capture_allowed,
                cloud_allowed=self._cloud_allowed,
                monitoring=self._monitoring,
                granted_at=self._granted_at,
                captures_this_session=self._captures,
                masked_fields_this_session=self._masked_fields,
                # Structural, not aspirational: nothing in this codebase writes
                # a screenshot to disk, so this counter can only ever be zero.
                screenshots_stored=0,
                last_capture_at=self._last_capture_at,
            )


class PermissionDenied(Exception):
    """Raised when the pipeline attempts capture without consent."""


def require_capture_permission(state: PrivacyState) -> None:
    if not state.capture_allowed:
        raise PermissionDenied(
            "Screen access has not been granted for this session. "
            "Turn on Merchant Mode screen reading to continue."
        )


CLOUD_WARNING = (
    "This will send text read from your screen to a cloud AI service. "
    "Sensitive details are masked first, but the text still leaves this computer. "
    "Local (Ollama) processing is the default and keeps everything on this machine."
)
