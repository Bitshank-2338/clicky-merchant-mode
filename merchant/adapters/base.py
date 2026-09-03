"""
Data adapter interface.

Two implementations exist: `DemoAdapter` (seeded synthetic data, always
available) and `RazorpayTestAdapter` (read-only calls against Razorpay test
mode, only when credentials are present).

Both are strictly READ-ONLY. There is deliberately no `create_*` or `refund_*`
method anywhere in this interface — the safety guarantee is structural, not a
runtime check that could be bypassed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from merchant.models import AdapterMode


class AdapterError(Exception):
    """Raised when the data source cannot answer. Never swallowed silently."""

    def __init__(self, message: str, code: str = "ADAPTER_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class DataResult:
    """Adapter output with provenance attached.

    `ok=False` means the caller must tell the merchant that data is unavailable.
    It must never fall back to inventing plausible rows.
    """

    ok: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    source: str = "demo_adapter"
    error: Optional[str] = None
    error_code: Optional[str] = None
    partial: bool = False
    missing_fields: list[str] = field(default_factory=list)

    @classmethod
    def failure(cls, message: str, code: str, source: str) -> "DataResult":
        return cls(ok=False, rows=[], source=source, error=message, error_code=code)


class DashboardAdapter(ABC):
    """Read-only view over a merchant's dashboard data."""

    mode: AdapterMode

    @abstractmethod
    def health(self) -> bool:
        """True when this adapter can serve requests right now."""

    @abstractmethod
    def settlements(self, limit: int = 10) -> DataResult: ...

    @abstractmethod
    def payments(self, limit: int = 25, status: Optional[str] = None) -> DataResult: ...

    @abstractmethod
    def refunds(self, limit: int = 25) -> DataResult: ...

    @abstractmethod
    def payment_links(self, limit: int = 25) -> DataResult: ...

    def failed_payments(self, limit: int = 25) -> DataResult:
        """Convenience view. Defaults to the `failed` slice of `payments`."""
        return self.payments(limit=limit, status="failed")

    @property
    def label(self) -> str:
        return (
            "Demo Mode (synthetic data)"
            if self.mode is AdapterMode.DEMO
            else "Razorpay Test Mode (read-only)"
        )
