"""
Adapter package for Clicky Merchant Mode.

Exposes the adapter interface, the always-available `DemoAdapter`, the
read-only `RazorpayTestAdapter`, and a `get_adapter(...)` factory that picks
between them.

The import of `razorpay_test` (and therefore of `httpx`) is guarded so that a
missing `httpx` install can never break demo mode, which has no such
dependency.
"""

from __future__ import annotations

import os
from typing import Optional, Union

from merchant.adapters.base import AdapterError, DashboardAdapter, DataResult
from merchant.adapters.demo import DemoAdapter
from merchant.models import AdapterMode

from typing import Optional, Type

# `httpx` is only needed for the Razorpay test adapter. Demo Mode must keep
# working without it, so a missing dependency degrades rather than crashes.
_RAZORPAY_ADAPTER: Optional[Type[DashboardAdapter]]
try:
    from merchant.adapters.razorpay_test import RazorpayTestAdapter, is_configured
    _RAZORPAY_ADAPTER = RazorpayTestAdapter
except ImportError:  # pragma: no cover - only happens if httpx is missing
    _RAZORPAY_ADAPTER = None

    def is_configured() -> bool:
        return False


__all__ = [
    "DashboardAdapter",
    "DataResult",
    "AdapterError",
    "DemoAdapter",
    "get_adapter",
]

# Only advertise the Razorpay adapter when it actually imported, so
# `from merchant.adapters import *` cannot fail on a missing httpx.
if _RAZORPAY_ADAPTER is not None:
    __all__.append("RazorpayTestAdapter")


def _is_test_key(key_id: Optional[str]) -> bool:
    return bool(key_id) and key_id.startswith("rzp_test_")


def get_adapter(
    mode: Union[str, AdapterMode, None] = None,
    scenario_id: Optional[str] = None,
) -> DashboardAdapter:
    """Returns the adapter for `mode`, falling back to `DemoAdapter` whenever
    Razorpay Test Mode is not safely usable.

    `mode` defaults to the `MERCHANT_ADAPTER` env var, then to "demo".
    Razorpay Test Mode is only returned when: `RazorpayTestAdapter` is
    importable, both credential env vars are set, and the configured key
    looks like a test key (`rzp_test_...`). Any other case — missing
    dependency, missing credentials, or a live-looking key — falls back to
    the demo adapter rather than risking a call against production data.
    """
    if mode is None:
        mode = os.environ.get("MERCHANT_ADAPTER", "demo")
    if isinstance(mode, AdapterMode):
        mode_value = mode.value
    else:
        mode_value = str(mode)

    if (
        mode_value == AdapterMode.RAZORPAY_TEST.value
        and _RAZORPAY_ADAPTER is not None
        and is_configured()
        and _is_test_key(os.environ.get("RAZORPAY_KEY_ID"))
    ):
        return _RAZORPAY_ADAPTER()

    return DemoAdapter(scenario_id)
