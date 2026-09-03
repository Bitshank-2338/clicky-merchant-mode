"""
Privacy tests.

The target for privacy violations is zero, so these are written as invariants
rather than examples: masked output is asserted to contain *no* recognisable
PII of any kind, not merely to differ from the input.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from merchant import masking
from merchant.audit import REDACTED, AuditLog
from merchant.masking import (
    contains_unmasked_pii,
    mask_contact,
    mask_customer_name,
    mask_dict,
    mask_email,
    mask_text,
)
from merchant.privacy import PermissionDenied, PrivacyState, require_capture_permission

REPO = Path(__file__).resolve().parent.parent


SENSITIVE_SAMPLES = [
    ("card", "Paid with card 4111 1111 1111 1111 today"),
    ("card_masked", "Card 4111 **** **** 1111 on file"),
    ("phone", "Call the customer on +91 98123 45678 please"),
    ("phone_bare", "Contact 9812345678 for the order"),
    ("email", "Receipt sent to rohit.verma@example.com already"),
    ("upi", "He paid from rohit@okhdfcbank just now"),
    ("api_key", "Key rzp_test_ABCdef123456 is in the config"),
    ("api_key_live", "Using rzp_live_EXAMPLEONLY987654 in production"),
    ("pan", "PAN ABCDE1234F was submitted"),
    ("aadhaar", "Aadhaar 1234 5678 9012 uploaded"),
    ("ifsc", "Bank IFSC HDFC0001234 for the transfer"),
    ("bearer", "Authorization: Bearer abcdefghijklmnop123456"),
]


@pytest.mark.parametrize("label,text", SENSITIVE_SAMPLES, ids=[s[0] for s in SENSITIVE_SAMPLES])
def test_masking_leaves_no_recognisable_pii(label: str, text: str) -> None:
    result = mask_text(text)
    leaks = contains_unmasked_pii(result.text)
    assert leaks == [], f"{label}: {leaks} survived masking -> {result.text!r}"
    assert result.total >= 1, f"{label}: nothing was masked at all"


def test_masking_preserves_surrounding_words() -> None:
    """Masking must not destroy the sentence — the merchant still needs to read it."""
    out = mask_text("Refund of Rs 500 to rohit@okhdfcbank was processed").text
    assert "Refund" in out and "processed" in out
    assert "okhdfcbank" not in out


def test_currency_amounts_are_not_mistaken_for_pii() -> None:
    """A rupee figure must survive masking, or every explanation breaks."""
    out = mask_text("Your settlement was ₹9,264 after ₹200 fees").text
    assert "9,264" in out
    assert "200" in out


def test_multiple_pii_in_one_string_all_masked() -> None:
    text = ("Customer Rohit Verma, phone +919812345678, email rohit@example.com, "
            "card 4111111111111111, key rzp_test_ABCdef123456")
    out = mask_text(text)
    assert contains_unmasked_pii(out.text) == []
    assert out.total >= 4


def test_field_level_maskers() -> None:
    assert mask_customer_name("Rohit Verma") == "R. V."
    assert mask_customer_name("") == "[NAME]"
    assert "9812345678" not in mask_contact("+919812345678")
    assert mask_contact("+919812345678").endswith("5678")
    assert mask_email("rohit.verma@example.com") == "r***@example.com"
    assert mask_email("not-an-email") == "[EMAIL]"


def test_mask_dict_recurses_and_covers_nested_descriptions() -> None:
    row = {
        "id": "pay_1",
        "customer_name": "Rohit Verma",
        "customer_contact": "+919812345678",
        "customer_email": "rohit@example.com",
        "amount": 250000,
        "notes": {"internal": "reach him at 9812345678 or rohit@example.com"},
        "tags": ["call 9812345678"],
    }
    out = mask_dict(row)
    blob = json.dumps(out, ensure_ascii=False)
    assert contains_unmasked_pii(blob) == []
    assert out["amount"] == 250000, "non-string values must pass through untouched"


def test_every_seed_row_masks_clean() -> None:
    """The whole demo dataset must survive masking with zero leaks."""
    seed = json.loads((REPO / "merchant" / "seed" / "dashboard_seed.json")
                      .read_text(encoding="utf-8"))
    masked = mask_dict(seed)
    blob = json.dumps(masked, ensure_ascii=False)
    assert contains_unmasked_pii(blob) == [], "seed data leaked PII after masking"


def test_assert_clean_raises_on_leak() -> None:
    with pytest.raises(ValueError):
        masking.assert_clean("call 9812345678", where="test sink")
    masking.assert_clean("nothing sensitive here", where="test sink")


# ── Permission gate ───────────────────────────────────────────────────────────


def test_capture_denied_until_permission_granted() -> None:
    state = PrivacyState()
    assert state.capture_allowed is False
    with pytest.raises(PermissionDenied):
        require_capture_permission(state)

    state.grant_permission()
    assert state.capture_allowed is True
    require_capture_permission(state)  # must not raise


def test_stop_monitoring_revokes_immediately_and_disables_cloud() -> None:
    state = PrivacyState()
    state.grant_permission()
    state.allow_cloud_inference(True)
    assert state.cloud_allowed is True

    state.stop_monitoring()
    assert state.capture_allowed is False
    assert state.monitoring is False
    assert state.cloud_allowed is False, "stopping must also cut cloud inference"
    with pytest.raises(PermissionDenied):
        require_capture_permission(state)


def test_cloud_inference_is_off_by_default() -> None:
    state = PrivacyState()
    state.grant_permission()
    assert state.cloud_allowed is False, "cloud inference must be opt-in, not opt-out"


def test_snapshot_reports_zero_stored_screenshots() -> None:
    state = PrivacyState()
    state.grant_permission()
    state.note_capture(masked_fields=3)
    state.note_capture(masked_fields=2)
    snap = state.snapshot()
    assert snap.screenshots_stored == 0
    assert snap.captures_this_session == 2
    assert snap.masked_fields_this_session == 5
    assert "Privacy ON" in snap.status_text()


# ── Non-persistence, checked structurally ─────────────────────────────────────


def test_no_module_writes_a_screenshot_to_disk() -> None:
    """Grep the shipped source for image-writing calls on capture paths.

    This is a structural guarantee, not a behavioural one: if nobody ever calls
    `Image.save`/`open(...,'wb')` on captured bytes, screenshots cannot leak to
    disk regardless of how the app is driven.
    """
    suspicious = re.compile(
        r"\.save\(\s*['\"][^'\"]*\.(png|jpg|jpeg|bmp)|"
        r"open\([^)]*\.(png|jpg|jpeg)['\"]\s*,\s*['\"]wb",
        re.IGNORECASE,
    )
    checked = 0
    for path in (REPO / "merchant").rglob("*.py"):
        checked += 1
        text = path.read_text(encoding="utf-8")
        assert not suspicious.search(text), f"{path} appears to write an image file"
    assert checked > 5, "sanity: expected to scan several merchant modules"


def test_capture_module_returns_bytes_not_paths() -> None:
    """`capture_active_window` must hand back in-memory bytes, never a filename."""
    src = (REPO / "screen" / "capture.py").read_text(encoding="utf-8")
    assert "jpeg_bytes" in src
    fn_src = src.split("def capture_active_window", 1)[1]
    assert ".save(" in fn_src and "BytesIO" in fn_src, "must serialise to memory"
    assert not re.search(r"open\([^)]*['\"]w", fn_src), "must not open a file for writing"


# ── The audit log must never become the leak ──────────────────────────────────


def test_audit_masks_entries() -> None:
    log = AuditLog()
    log.record("question", "refund rohit@example.com ka 9812345678 par")
    entry = log.events()[0]
    assert contains_unmasked_pii(entry.detail) == []


def test_audit_redacts_rather_than_writing_surviving_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    """If masking ever failed, the entry is withheld instead of persisted."""
    monkeypatch.setattr("merchant.audit.mask_text",
                        lambda text: masking.MaskResult(text, {}))
    log = AuditLog()
    log.record("question", "card 4111111111111111")
    assert log.events()[0].detail == REDACTED


def test_audit_does_not_persist_without_explicit_path(tmp_path: Path) -> None:
    log = AuditLog(path=None)
    log.record("question", "hello")
    assert list(tmp_path.iterdir()) == []
    assert len(log) == 1


def test_audit_persists_only_masked_text_when_path_given(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    log = AuditLog(path=str(target))
    log.record("question", "refund to rohit@example.com")
    written = target.read_text(encoding="utf-8")
    assert contains_unmasked_pii(written) == []
    assert "rohit@example.com" not in written


def test_audit_is_bounded() -> None:
    log = AuditLog(max_events=10)
    for i in range(50):
        log.record("question", f"question number {i}")
    assert len(log) == 10


def test_privacy_state_is_not_serialisable_to_disk_by_accident() -> None:
    """PrivacyState must hold no screen content that could be pickled out."""
    state = PrivacyState()
    state.grant_permission()
    state.note_capture(4)
    for name, value in vars(state).items():
        assert not isinstance(value, (bytes, bytearray)), (
            f"PrivacyState.{name} holds raw bytes — screen content must not be retained"
        )


def test_privacy_module_has_no_network_imports() -> None:
    src = inspect.getsource(__import__("merchant.privacy", fromlist=["x"]))
    for forbidden in ("import requests", "import httpx", "urllib.request", "socket."):
        assert forbidden not in src, f"privacy module must not reach the network ({forbidden})"
