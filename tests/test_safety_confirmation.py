"""
Safety tests.

Merchant Mode's core promise is that it never moves money. These tests attack
that promise from several angles: the confirmation token lifecycle, the
structural absence of write calls in the adapters, and the refusal path when a
merchant simply tells Clicky to "refund kar do".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from merchant.audit import (
    KIND_ACTION_BLOCKED,
    KIND_CONFIRM_APPROVED,
    KIND_CONFIRM_REJECTED,
    KIND_CONFIRM_REQUESTED,
    AuditLog,
)
from merchant.confirm import (
    NEVER_AUTOMATED,
    ConfirmationError,
    ConfirmationManager,
    blocked_action_message,
)
from merchant.masking import contains_unmasked_pii

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def manager() -> tuple[ConfirmationManager, AuditLog]:
    log = AuditLog()
    return ConfirmationManager(log, ttl_seconds=60.0), log


# ── The confirmation contract ─────────────────────────────────────────────────


def test_request_shows_action_amount_and_masked_customer(manager) -> None:
    mgr, log = manager
    req = mgr.request(
        kind="issue_refund",
        summary="Refund order #1183",
        amount_paise=50000,
        customer_name="Anita Desai",
        customer_contact="+919900112233",
    )
    assert req.amount_text == "₹500"
    assert "A. D." in req.masked_customer
    assert contains_unmasked_pii(req.masked_customer) == []
    assert "9900112233" not in req.masked_customer
    assert req.warning, "a sensitive action must carry a warning"
    assert req.irreversible is True
    assert log.events(kind=KIND_CONFIRM_REQUESTED), "request must be audited"


def test_approval_returns_authorisation_not_execution(manager) -> None:
    mgr, log = manager
    req = mgr.request("issue_refund", "Refund order #1183", 50000, "Anita Desai")
    auth = mgr.approve(req.action_id)
    assert auth.executed is False, "approval must never mean 'done'"
    assert "does not perform" in auth.execution_note
    assert log.events(kind=KIND_CONFIRM_APPROVED)


def test_token_cannot_be_redeemed_twice(manager) -> None:
    """A double-click must not become a double refund."""
    mgr, log = manager
    req = mgr.request("issue_refund", "Refund order #1183", 50000)
    mgr.approve(req.action_id)

    with pytest.raises(ConfirmationError) as exc:
        mgr.approve(req.action_id)
    assert exc.value.code == "ALREADY_CONSUMED"
    assert log.events(kind=KIND_ACTION_BLOCKED), "duplicate must be audited as blocked"


def test_expired_confirmation_is_refused() -> None:
    log = AuditLog()
    mgr = ConfirmationManager(log, ttl_seconds=30.0)
    req = mgr.request("issue_refund", "Refund order #1183", 50000, now=1000.0)

    with pytest.raises(ConfirmationError) as exc:
        mgr.approve(req.action_id, now=1031.0)
    assert exc.value.code == "EXPIRED"


def test_confirmation_valid_just_inside_the_window() -> None:
    mgr = ConfirmationManager(AuditLog(), ttl_seconds=30.0)
    req = mgr.request("issue_refund", "Refund", 50000, now=1000.0)
    auth = mgr.approve(req.action_id, now=1029.9)
    assert auth.action_id == req.action_id


def test_unknown_token_is_refused_and_audited(manager) -> None:
    mgr, log = manager
    with pytest.raises(ConfirmationError) as exc:
        mgr.approve("not-a-real-token")
    assert exc.value.code == "UNKNOWN_ACTION"
    assert log.events(kind=KIND_ACTION_BLOCKED)


def test_rejection_is_audited_and_invalidates_the_token(manager) -> None:
    mgr, log = manager
    req = mgr.request("issue_refund", "Refund order #1183", 50000)
    mgr.reject(req.action_id)
    assert log.events(kind=KIND_CONFIRM_REJECTED)
    with pytest.raises(ConfirmationError):
        mgr.approve(req.action_id)


def test_purge_expired_clears_stale_tokens() -> None:
    mgr = ConfirmationManager(AuditLog(), ttl_seconds=10.0)
    mgr.request("issue_refund", "a", 100, now=1000.0)
    mgr.request("issue_refund", "b", 100, now=1000.0)
    assert mgr.pending_count() == 2
    assert mgr.purge_expired(now=1011.0) == 2
    assert mgr.pending_count() == 0


def test_amount_not_shown_when_unknown(manager) -> None:
    """Never fabricate an amount for a confirmation dialog."""
    mgr, _ = manager
    req = mgr.request("issue_refund", "Refund something", amount_paise=None)
    assert req.amount_text == "amount not shown"
    assert not re.search(r"₹\s?\d", req.amount_text)


def test_every_never_automated_kind_has_a_warning(manager) -> None:
    mgr, _ = manager
    for kind in sorted(NEVER_AUTOMATED):
        req = mgr.request(kind, f"test {kind}", 10000)
        assert req.warning.strip(), f"{kind} has no warning text"
        assert req.irreversible is True


@pytest.mark.parametrize("language", ["english", "hindi", "hinglish"])
def test_blocked_action_message_refuses_in_every_language(language: str) -> None:
    msg = blocked_action_message("issue_refund", language)
    assert msg.strip()
    lowered = msg.lower()
    assert any(tok in lowered for tok in ("not", "nahi", "नहीं")), (
        f"{language} refusal does not actually refuse: {msg}"
    )


# ── Structural read-only guarantee ────────────────────────────────────────────


WRITE_CALL = re.compile(
    r"\.(post|put|patch|delete)\s*\(|"
    r"['\"](POST|PUT|PATCH|DELETE)['\"]",
    re.IGNORECASE,
)


def test_adapters_contain_no_write_calls() -> None:
    """No adapter may contain code that could mutate a Razorpay account."""
    adapters = list((REPO / "merchant" / "adapters").glob("*.py"))
    assert adapters, "no adapter modules found"
    for path in adapters:
        text = path.read_text(encoding="utf-8")
        # Strip comments and docstrings so prose about POST is not a false hit.
        code = re.sub(r"#.*", "", text)
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        code = re.sub(r"'''[\s\S]*?'''", "", code)
        found = WRITE_CALL.findall(code)
        assert not found, f"{path.name} contains a write call: {found}"


def test_adapter_interface_exposes_no_mutating_methods() -> None:
    from merchant.adapters.base import DashboardAdapter

    forbidden = ("create", "issue", "refund_payment", "send", "update", "delete",
                 "cancel", "capture")
    for name in dir(DashboardAdapter):
        if name.startswith("_"):
            continue
        assert not any(name.startswith(f) for f in forbidden), (
            f"DashboardAdapter.{name} looks like a mutating method"
        )


def test_razorpay_adapter_refuses_live_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_SHOULDNEVERRUN")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "supersecretvalue")
    from merchant.adapters.razorpay_test import RazorpayTestAdapter

    adapter = RazorpayTestAdapter()
    assert adapter.health() is False
    result = adapter.settlements()
    assert result.ok is False
    assert result.error_code == "LIVE_KEY_REFUSED"
    assert "supersecretvalue" not in (result.error or "")
    assert "rzp_live_SHOULDNEVERRUN" not in (result.error or "")


def test_razorpay_adapter_never_leaks_secret_on_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_ABCDEF123456")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "topsecretsecret123")
    from merchant.adapters.razorpay_test import RazorpayTestAdapter

    adapter = RazorpayTestAdapter()
    result = adapter.settlements()  # no network in CI -> NETWORK_ERROR
    blob = f"{result.error} {result.error_code}"
    assert "topsecretsecret123" not in blob
    assert contains_unmasked_pii(blob) == []


def test_adapter_constructible_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    from merchant.adapters.razorpay_test import RazorpayTestAdapter

    adapter = RazorpayTestAdapter()
    assert adapter.health() is False
    assert adapter.settlements().ok is False


def test_get_adapter_defaults_to_demo_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("MERCHANT_ADAPTER", raising=False)
    from merchant.adapters import get_adapter
    from merchant.models import AdapterMode

    adapter = get_adapter()
    assert adapter.mode is AdapterMode.DEMO
    assert adapter.health() is True


def test_no_credentials_are_committed() -> None:
    """A real key must never end up in the repo."""
    patterns = [re.compile(r"rzp_live_[A-Za-z0-9]{8,}")]
    # A test key literal is fine in tests; a live key never is.
    skip_dirs = {".git", "__pycache__", "node_modules", ".pytest_cache"}
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".json", ".js", ".md",
                                                     ".html", ".txt", ".example"}:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for rx in patterns:
            for hit in rx.findall(text):
                # Our own safety tests deliberately construct a fake live key.
                assert "SHOULDNEVERRUN" in text or "EXAMPLE" in hit.upper(), (
                    f"possible live credential in {path}: {hit}"
                )
