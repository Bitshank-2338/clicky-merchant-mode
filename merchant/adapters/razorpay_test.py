"""
Razorpay Test Mode adapter — read-only calls against the live Razorpay API,
but ONLY ever a `rzp_test_...` key.

Why this exists: Merchant Mode is allowed to explain a merchant's *real* test
data instead of the seeded demo, but it must never be able to touch a live
account. Razorpay does not offer a separate "test API host" — test mode is
selected purely by which key you authenticate with. That means the only
technical guardrail available to us is to inspect the key prefix ourselves
and refuse anything that isn't `rzp_test_`. This is enforced in `health()`
and independently in every public read method, so there is no path through
this adapter that can reach a live key's data.

READ-ONLY, structurally: this file only ever issues HTTP GET. There is no
method here, public or private, that builds a POST/PUT/PATCH/DELETE request,
and none should ever be added — payment links, refunds, orders and payments
are all created/modified elsewhere (the merchant dashboard, not Clicky).
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from merchant.adapters.base import DashboardAdapter, DataResult
from merchant.models import AdapterMode

BASE_URL = "https://api.razorpay.com/v1"
REQUEST_TIMEOUT_SECONDS = 10.0
TEST_KEY_PREFIX = "rzp_test_"

_SOURCE = "razorpay_test_api"

# Settlement fields the list endpoint does not expose. Razorpay's
# `GET /settlements` response gives id/amount/status/utr/created_at but not a
# gross/fees/tax/refunds/adjustments/disputes breakdown. We report these as
# genuinely missing rather than guessing or defaulting to zero.
_SETTLEMENT_UNAVAILABLE_FIELDS = (
    "gross_amount",
    "fees",
    "tax",
    "refunds",
    "adjustments",
    "disputes",
)


def is_configured() -> bool:
    """True when both Razorpay credential env vars are present (non-empty)."""
    return bool(os.environ.get("RAZORPAY_KEY_ID")) and bool(
        os.environ.get("RAZORPAY_KEY_SECRET")
    )


def _is_test_key(key_id: Optional[str]) -> bool:
    return bool(key_id) and key_id.startswith(TEST_KEY_PREFIX)


class RazorpayTestAdapter(DashboardAdapter):
    """Read-only adapter over a merchant's own Razorpay TEST MODE account.

    Construction never raises, even with no credentials present or a
    malformed environment — every failure mode surfaces later, per-call, as
    a `DataResult.failure(...)`.
    """

    mode = AdapterMode.RAZORPAY_TEST

    def __init__(self) -> None:
        self._key_id: Optional[str] = os.environ.get("RAZORPAY_KEY_ID")
        self._key_secret: Optional[str] = os.environ.get("RAZORPAY_KEY_SECRET")

    # ── Safety gate ──────────────────────────────────────────────────────────

    def _refuse_reason(self) -> Optional[tuple[str, str]]:
        """Returns (code, message) if this adapter must refuse to talk to the
        API right now, or None if it's safe to proceed. Never includes the
        actual key value in the message."""
        if not self._key_id or not self._key_secret:
            return (
                "NOT_CONFIGURED",
                "Razorpay Test Mode is not configured. Set RAZORPAY_KEY_ID "
                "and RAZORPAY_KEY_SECRET to use it.",
            )
        if not _is_test_key(self._key_id):
            return (
                "LIVE_KEY_REFUSED",
                "Merchant Mode only ever talks to Razorpay TEST mode. The "
                "configured RAZORPAY_KEY_ID does not look like a test key "
                "(it must start with 'rzp_test_'), so this adapter refuses "
                "to make any request.",
            )
        return None

    def health(self) -> bool:
        return self._refuse_reason() is None

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _client(self) -> httpx.Client:
        # _key_id/_key_secret are guaranteed present by the caller's guard.
        assert self._key_id is not None and self._key_secret is not None
        return httpx.Client(
            base_url=BASE_URL,
            auth=(self._key_id, self._key_secret),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def _get(self, path: str, params: dict[str, Any]) -> DataResult | dict[str, Any]:
        """Issues a single GET. Returns the parsed JSON body on success, or a
        `DataResult.failure(...)` ready to hand straight back to the caller."""
        refusal = self._refuse_reason()
        if refusal:
            code, message = refusal
            return DataResult.failure(message=message, code=code, source=_SOURCE)

        try:
            with self._client() as client:
                response = client.get(path, params=params)
        except httpx.TimeoutException:
            return DataResult.failure(
                message="Timed out reaching the Razorpay API.",
                code="NETWORK_ERROR",
                source=_SOURCE,
            )
        except httpx.RequestError:
            return DataResult.failure(
                message="Could not reach the Razorpay API (network error).",
                code="NETWORK_ERROR",
                source=_SOURCE,
            )

        if response.status_code in (401, 403):
            return DataResult.failure(
                message="Razorpay rejected the configured credentials.",
                code="AUTH_ERROR",
                source=_SOURCE,
            )
        if response.status_code >= 400:
            return DataResult.failure(
                message=f"Razorpay API returned HTTP {response.status_code}.",
                code="API_ERROR",
                source=_SOURCE,
            )

        try:
            body = response.json()
        except ValueError:
            return DataResult.failure(
                message="Razorpay API returned a response that could not be parsed as JSON.",
                code="MALFORMED_RESPONSE",
                source=_SOURCE,
            )

        if not isinstance(body, dict):
            return DataResult.failure(
                message="Razorpay API returned an unexpected response shape.",
                code="MALFORMED_RESPONSE",
                source=_SOURCE,
            )

        return body

    # ── Row mapping ──────────────────────────────────────────────────────────
    # Each mapper turns one Razorpay API object into the row shape the demo
    # adapter emits (see merchant/seed/dashboard_seed.json), so merchant/facts.py
    # works unchanged regardless of which adapter produced the row.

    @staticmethod
    def _map_settlement(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        settlement_id = str(item.get("id", ""))
        row: dict[str, Any] = {
            "id": settlement_id,
            "status": item.get("status"),
            "period_start": None,
            "period_end": None,
            "settled_on": _epoch_to_date(item.get("created_at")),
            "utr": item.get("utr"),
            "net_amount": item.get("amount"),
        }
        missing: list[str] = []
        for fld in _SETTLEMENT_UNAVAILABLE_FIELDS:
            row[fld] = None
            missing.append(f"{settlement_id}.{fld}")
        # period_start/period_end are also not on the list endpoint.
        for fld in ("period_start", "period_end"):
            missing.append(f"{settlement_id}.{fld}")
        return row, missing

    @staticmethod
    def _map_payment(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "amount": item.get("amount"),
            "status": item.get("status"),
            "method": item.get("method"),
            "created_at": _epoch_to_iso(item.get("created_at")),
            "customer_name": (item.get("notes") or {}).get("name")
            if isinstance(item.get("notes"), dict)
            else None,
            "customer_contact": item.get("contact"),
            "customer_email": item.get("email"),
            "description": item.get("description"),
            "fee": item.get("fee"),
            "tax": item.get("tax"),
            "error_code": item.get("error_code"),
            "error_source": item.get("error_source"),
            "error_reason": item.get("error_reason"),
            "error_description": item.get("error_description"),
        }

    @staticmethod
    def _map_refund(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "payment_id": item.get("payment_id"),
            "amount": item.get("amount"),
            "type": "partial" if item.get("speed_processed") == "instant" else item.get("status"),
            "status": item.get("status"),
            "created_at": _epoch_to_iso(item.get("created_at")),
            "speed": item.get("speed_processed") or item.get("speed_requested"),
            "reason": item.get("notes", {}).get("reason")
            if isinstance(item.get("notes"), dict)
            else None,
        }

    @staticmethod
    def _map_payment_link(item: dict[str, Any]) -> dict[str, Any]:
        customer = item.get("customer") if isinstance(item.get("customer"), dict) else {}
        return {
            "id": item.get("id"),
            "amount": item.get("amount"),
            "status": item.get("status"),
            "description": item.get("description"),
            "created_at": _epoch_to_iso(item.get("created_at")),
            "expire_by": _epoch_to_iso(item.get("expire_by")),
            "customer_name": customer.get("name"),
            "customer_contact": customer.get("contact"),
            "customer_email": customer.get("email"),
            "short_url": item.get("short_url"),
        }

    # ── Reads ────────────────────────────────────────────────────────────────

    def settlements(self, limit: int = 10) -> DataResult:
        body = self._get("/settlements", {"count": limit, "skip": 0})
        if isinstance(body, DataResult):
            return body
        items = body.get("items")
        if not isinstance(items, list):
            return DataResult.failure(
                message="Razorpay settlements response had no 'items' list.",
                code="MALFORMED_RESPONSE",
                source=_SOURCE,
            )
        rows: list[dict[str, Any]] = []
        missing_fields: list[str] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            row, missing = self._map_settlement(raw)
            rows.append(row)
            missing_fields.extend(missing)
        return DataResult(
            ok=True,
            rows=rows,
            source=_SOURCE,
            partial=bool(missing_fields),
            missing_fields=missing_fields,
        )

    def payments(self, limit: int = 25, status: Optional[str] = None) -> DataResult:
        # The list API can't filter by status server-side, so when a status
        # filter is requested we pull a larger page (Razorpay's max) before
        # filtering client-side, to avoid under-filling `limit`.
        fetch_count = 100 if status else limit
        body = self._get("/payments", {"count": fetch_count, "skip": 0})
        if isinstance(body, DataResult):
            return body
        items = body.get("items")
        if not isinstance(items, list):
            return DataResult.failure(
                message="Razorpay payments response had no 'items' list.",
                code="MALFORMED_RESPONSE",
                source=_SOURCE,
            )
        rows = [self._map_payment(raw) for raw in items if isinstance(raw, dict)]
        if status:
            rows = [r for r in rows if str(r.get("status", "")).lower() == status.lower()]
        return DataResult(ok=True, rows=rows[:limit], source=_SOURCE)

    def refunds(self, limit: int = 25) -> DataResult:
        body = self._get("/refunds", {"count": limit, "skip": 0})
        if isinstance(body, DataResult):
            return body
        items = body.get("items")
        if not isinstance(items, list):
            return DataResult.failure(
                message="Razorpay refunds response had no 'items' list.",
                code="MALFORMED_RESPONSE",
                source=_SOURCE,
            )
        rows = [self._map_refund(raw) for raw in items if isinstance(raw, dict)]
        return DataResult(ok=True, rows=rows[:limit], source=_SOURCE)

    def payment_links(self, limit: int = 25) -> DataResult:
        body = self._get("/payment_links", {"count": limit, "skip": 0})
        if isinstance(body, DataResult):
            return body
        items = body.get("items")
        if not isinstance(items, list):
            return DataResult.failure(
                message="Razorpay payment_links response had no 'items' list.",
                code="MALFORMED_RESPONSE",
                source=_SOURCE,
            )
        rows = [self._map_payment_link(raw) for raw in items if isinstance(raw, dict)]
        return DataResult(ok=True, rows=rows[:limit], source=_SOURCE)


def _epoch_to_iso(value: Any) -> Optional[str]:
    """Razorpay timestamps are Unix epoch seconds. Converts to an ISO 8601
    string in UTC, or None if the value is missing/unparseable."""
    if value is None:
        return None
    try:
        import datetime

        return (
            datetime.datetime.fromtimestamp(int(value), tz=datetime.timezone.utc)
            .isoformat()
        )
    except (ValueError, TypeError, OSError):
        return None


def _epoch_to_date(value: Any) -> Optional[str]:
    iso = _epoch_to_iso(value)
    return iso[:10] if iso else None
