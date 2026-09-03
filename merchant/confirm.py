"""
Confirmation gate for sensitive actions.

Merchant Mode is read-only by design, so this module never *performs* anything.
What it does is model the promise the product makes: if a flow ever reached the
point of touching money, a human would have to look at the exact amount and the
masked customer and say yes, within a short window.

Concretely it guarantees:

* every sensitive action gets an explicit, single-use confirmation token;
* the confirmation shows the action, the exact amount and a masked customer;
* tokens expire (default 90 seconds) — a stale "yes" is not a yes;
* a token cannot be redeemed twice (no duplicate refunds from a double-click);
* approval and rejection are both written to the audit trail;
* redeeming a token returns an *authorisation*, not an effect. Executing it is
  deliberately left to the merchant in the real dashboard.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from merchant.audit import (
    KIND_ACTION_BLOCKED,
    KIND_CONFIRM_APPROVED,
    KIND_CONFIRM_EXPIRED,
    KIND_CONFIRM_REJECTED,
    KIND_CONFIRM_REQUESTED,
    AuditLog,
)
from merchant.masking import mask_contact, mask_customer_name
from merchant.models import Money, PendingAction

DEFAULT_TTL_SECONDS = 90.0

# Actions Merchant Mode will never perform, whatever the user says. Requesting
# one produces a teaching response plus a blocked-action audit entry.
NEVER_AUTOMATED = frozenset({
    "issue_refund",
    "send_payment_link",
    "message_customer",
    "create_payment_link",
    "cancel_payment",
    "settle_now",
})


class ConfirmationError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ConfirmationRequest:
    """What the confirmation modal renders. All customer data pre-masked."""

    action_id: str
    kind: str
    title: str
    summary: str
    amount_text: str
    masked_customer: str
    expires_in: float
    warning: str
    irreversible: bool = True


@dataclass
class Authorisation:
    """Proof a human approved an action. Not an execution result."""

    action_id: str
    kind: str
    approved_at: float
    summary: str
    executed: bool = False
    execution_note: str = (
        "Merchant Mode does not perform this action. Complete it yourself in the "
        "Razorpay dashboard — you stay in control of every rupee."
    )


class ConfirmationManager:
    """Issues, expires and redeems single-use confirmation tokens."""

    def __init__(self, audit: AuditLog, ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self._lock = threading.RLock()
        self._pending: dict[str, PendingAction] = {}
        self._audit = audit
        self._ttl = float(ttl_seconds)

    # ── Issuing ──────────────────────────────────────────────────────────────

    def request(
        self,
        kind: str,
        summary: str,
        amount_paise: Optional[int] = None,
        customer_name: str = "",
        customer_contact: str = "",
        now: Optional[float] = None,
    ) -> ConfirmationRequest:
        """Create a pending confirmation. Does not perform anything."""
        t = now if now is not None else time.time()
        action_id = uuid.uuid4().hex[:16]

        amount_text = Money(int(amount_paise)).format() if amount_paise is not None \
            else "amount not shown"

        masked = _mask_customer(customer_name, customer_contact)

        pending = PendingAction(
            action_id=action_id,
            kind=kind,
            summary=summary,
            amount_text=amount_text,
            masked_customer=masked,
            created_at=t,
            expires_at=t + self._ttl,
        )
        with self._lock:
            self._pending[action_id] = pending

        self._audit.record(
            KIND_CONFIRM_REQUESTED,
            f"{kind}: {summary} | {amount_text} | {masked}",
            outcome="awaiting_confirmation",
        )

        return ConfirmationRequest(
            action_id=action_id,
            kind=kind,
            title=_title_for(kind),
            summary=summary,
            amount_text=amount_text,
            masked_customer=masked,
            expires_in=self._ttl,
            warning=_warning_for(kind),
            irreversible=kind in NEVER_AUTOMATED,
        )

    # ── Redeeming ────────────────────────────────────────────────────────────

    def approve(self, action_id: str, now: Optional[float] = None) -> Authorisation:
        """Redeem a token. Raises rather than silently accepting a bad one."""
        t = now if now is not None else time.time()
        with self._lock:
            pending = self._pending.get(action_id)

            if pending is None:
                self._audit.record(KIND_ACTION_BLOCKED,
                                   f"unknown confirmation token {action_id}",
                                   outcome="blocked")
                raise ConfirmationError(
                    "That confirmation is not valid any more. Please ask again.",
                    code="UNKNOWN_ACTION")

            if pending.consumed:
                self._audit.record(KIND_ACTION_BLOCKED,
                                   f"duplicate approval of {pending.kind}",
                                   outcome="blocked")
                raise ConfirmationError(
                    "This was already confirmed once. I will not repeat it — "
                    "that is how double refunds happen.",
                    code="ALREADY_CONSUMED")

            if pending.is_expired(t):
                del self._pending[action_id]
                self._audit.record(KIND_CONFIRM_EXPIRED,
                                   f"{pending.kind}: {pending.summary}",
                                   outcome="expired")
                raise ConfirmationError(
                    "That confirmation timed out. Please start again so you can "
                    "check the amount fresh.",
                    code="EXPIRED")

            pending.consumed = True

        self._audit.record(
            KIND_CONFIRM_APPROVED,
            f"{pending.kind}: {pending.summary} | {pending.amount_text} | "
            f"{pending.masked_customer}",
            outcome="approved",
            actor="merchant",
        )
        return Authorisation(
            action_id=action_id,
            kind=pending.kind,
            approved_at=t,
            summary=pending.summary,
        )

    def reject(self, action_id: str) -> None:
        with self._lock:
            pending = self._pending.pop(action_id, None)
        detail = f"{pending.kind}: {pending.summary}" if pending else action_id
        self._audit.record(KIND_CONFIRM_REJECTED, detail, outcome="rejected")

    # ── Housekeeping ─────────────────────────────────────────────────────────

    def get(self, action_id: str) -> Optional[PendingAction]:
        with self._lock:
            return self._pending.get(action_id)

    def purge_expired(self, now: Optional[float] = None) -> int:
        t = now if now is not None else time.time()
        with self._lock:
            stale = [k for k, v in self._pending.items() if v.is_expired(t)]
            for k in stale:
                del self._pending[k]
        for _ in stale:
            self._audit.record(KIND_CONFIRM_EXPIRED, "confirmation expired",
                               outcome="expired")
        return len(stale)

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for v in self._pending.values() if not v.consumed)


def _mask_customer(name: str, contact: str) -> str:
    parts = []
    if name:
        parts.append(mask_customer_name(name))
    if contact:
        parts.append(mask_contact(contact))
    return " · ".join(parts) if parts else "customer not shown"


_TITLES = {
    "issue_refund": "Confirm refund",
    "create_payment_link": "Confirm payment link",
    "send_payment_link": "Confirm sending this link",
    "message_customer": "Confirm message to customer",
    "cancel_payment": "Confirm cancellation",
    "settle_now": "Confirm instant settlement",
}


def _title_for(kind: str) -> str:
    return _TITLES.get(kind, "Please confirm")


_WARNINGS = {
    "issue_refund": (
        "A refund cannot be undone. The money goes back to the customer and the "
        "fees on the original payment are not returned to you."
    ),
    "create_payment_link": (
        "A payment link asks a real customer for real money. Check the amount "
        "before it goes out."
    ),
    "send_payment_link": "Once sent, the customer receives this immediately.",
    "message_customer": "This message will reach a real person.",
    "cancel_payment": "Cancelling cannot be undone.",
    "settle_now": "Instant settlement usually carries an extra fee.",
}


def _warning_for(kind: str) -> str:
    return _WARNINGS.get(
        kind, "Please check the details carefully — this may not be reversible."
    )


def blocked_action_message(kind: str, language: str = "english") -> str:
    """What Clicky says when asked to just do a sensitive thing itself."""
    if language == "hindi":
        return ("मैं यह काम खुद नहीं कर सकती। मैं आपको हर कदम दिखा सकती हूँ, "
                "लेकिन आखिरी बटन आपको ही दबाना होगा — पैसा आपका है।")
    if language == "hinglish":
        return ("Main ye kaam khud nahi kar sakti. Main aapko har step dikha sakti hoon, "
                "lekin final button aapko hi dabana hoga — paisa aapka hai.")
    return ("I will not do this for you. I can show you every step, but the final "
            "button has to be yours — it is your money.")
