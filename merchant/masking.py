"""
Sensitive-data masking.

This runs on *every* piece of screen-derived text before it reaches an LLM, a
log line, an audit record, or the UI. It is the single chokepoint for PII, so
it is deliberately conservative: it would rather over-mask a harmless string
than let a card number through.

Order matters. Longer, more specific patterns run first so that (for example) a
card number is not first chewed up by the generic long-digit rule.

Nothing here is network-aware and nothing is stored — callers pass a string in
and get a masked string out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Pattern

__all__ = [
    "MaskResult",
    "mask_text",
    "mask_customer_name",
    "mask_contact",
    "mask_email",
    "mask_dict",
    "contains_unmasked_pii",
]


MASK_TOKENS = {
    "card": "[CARD]",
    "upi": "[UPI]",
    "email": "[EMAIL]",
    "phone": "[PHONE]",
    "api_key": "[API_KEY]",
    "ifsc": "[IFSC]",
    "account": "[BANK_AC]",
    "pan": "[PAN]",
    "aadhaar": "[AADHAAR]",
    "name": "[NAME]",
}


@dataclass
class MaskResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _c(pattern: str, flags: int = 0) -> Pattern[str]:
    return re.compile(pattern, flags)


# ── Patterns, most specific first ─────────────────────────────────────────────
#
# Each rule is (kind, compiled regex). A rule may use a capture group named
# `keep` for a fragment that survives masking (e.g. the last four digits).

_RULES: list[tuple[str, Pattern[str]]] = [
    # Razorpay / generic API secrets. Run first: these look like nothing else.
    ("api_key", _c(r"\brzp_(?:live|test)_[A-Za-z0-9]{6,}\b")),
    ("api_key", _c(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("api_key", _c(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b")),
    ("api_key", _c(r"\b[A-Za-z0-9_\-]{0,12}(?:secret|token|apikey|api_key)"
                   r"[\"'\s:=]+[A-Za-z0-9._\-]{12,}\b", re.IGNORECASE)),

    # Aadhaar: 12 digits, often spaced 4-4-4. Before the card rule (both are
    # long digit runs) because Aadhaar has its own token.
    ("aadhaar", _c(r"\b\d{4}[ \-]?\d{4}[ \-]?\d{4}\b(?!\d)")),

    # Card numbers: 13-19 digits, optionally separated. Also masked-with-stars
    # forms the dashboard itself renders, e.g. "4111 **** **** 1111".
    ("card", _c(r"\b(?:\d[ \-]?){12,18}\d\b")),
    ("card", _c(r"\b\d{4}[ \-]?(?:[*Xx]{4}[ \-]?){2}(?P<keep>\d{4})\b")),
    ("card", _c(r"\b(?:[*Xx]{4}[ \-]?){3}(?P<keep>\d{4})\b")),

    # PAN: 5 letters, 4 digits, 1 letter.
    ("pan", _c(r"\b[A-Z]{5}\d{4}[A-Z]\b")),

    # IFSC: 4 letters, 0, 6 alphanumerics.
    ("ifsc", _c(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),

    # Email before UPI — an email also matches the UPI shape.
    ("email", _c(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),

    # UPI VPA: handle@psp where the psp half has no dot.
    ("upi", _c(r"\b[A-Za-z0-9._\-]{2,}@[A-Za-z][A-Za-z0-9]{1,}\b")),

    # Indian mobile numbers. Written every which way in practice — "9812345678",
    # "+91 98123 45678", "0981-234-5678" — so separators are allowed between
    # digits. The comma is deliberately NOT a separator, otherwise "₹9,264"
    # would be eaten as a phone number.
    ("phone", _c(r"(?:\+?91[\-\s]?|\b0)?[6-9](?:\d[\-\s]?){8}\d\b")),

    # Bank account numbers: 9-18 digits when explicitly labelled.
    ("account", _c(r"\b(?:a/c|acc(?:ount)?)\.?\s*(?:no\.?|number)?\s*[:#]?\s*"
                   r"\d{9,18}\b", re.IGNORECASE)),
]


def mask_text(text: str) -> MaskResult:
    """Mask every recognised sensitive pattern in `text`.

    Returns the masked string plus a count per kind, so callers can surface
    "12 sensitive fields hidden" without ever seeing the originals.
    """
    if not text:
        return MaskResult("", {})

    counts: dict[str, int] = {}
    out = text

    for kind, rx in _RULES:
        token = MASK_TOKENS[kind]

        def _sub(m: re.Match[str], _token: str = token, _kind: str = kind) -> str:
            counts[_kind] = counts.get(_kind, 0) + 1
            try:
                keep = m.groupdict().get("keep")
            except IndexError:
                keep = None
            return f"{_token}{keep}" if keep else _token

        out = rx.sub(_sub, out)

    return MaskResult(out, counts)


# ── Field-level helpers ───────────────────────────────────────────────────────


def mask_customer_name(name: str) -> str:
    """'Rohit Verma' -> 'R. V.'  Enough to confirm identity, not to identify."""
    if not name or not name.strip():
        return "[NAME]"
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    initials = [f"{p[0].upper()}." for p in parts if p[0].isalpha()]
    return " ".join(initials) if initials else "[NAME]"


def mask_contact(contact: str) -> str:
    """'+919812345678' -> '+91 ****** 5678'. Keeps the last four for matching."""
    if not contact:
        return "[PHONE]"
    digits = re.sub(r"\D", "", contact)
    if len(digits) < 4:
        return "[PHONE]"
    return f"+91 ****** {digits[-4:]}" if len(digits) >= 10 else f"****{digits[-4:]}"


def mask_email(email: str) -> str:
    """'rohit.verma@example.com' -> 'r***@example.com'."""
    if not email or "@" not in email:
        return "[EMAIL]"
    local, _, domain = email.partition("@")
    head = local[0] if local else "?"
    return f"{head}***@{domain}"


_SENSITIVE_KEYS = {
    "customer_name": mask_customer_name,
    "name": mask_customer_name,
    "customer_contact": mask_contact,
    "contact": mask_contact,
    "phone": mask_contact,
    "customer_email": mask_email,
    "email": mask_email,
}


def mask_dict(obj: object) -> object:
    """Recursively mask a JSON-ish structure.

    Known PII keys use their field-specific masker; every other string value is
    run through `mask_text` so a phone number hiding inside a description field
    is still caught.
    """
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for k, v in obj.items():
            masker = _SENSITIVE_KEYS.get(str(k).lower())
            if masker and isinstance(v, str):
                out[k] = masker(v)
            else:
                out[k] = mask_dict(v)
        return out
    if isinstance(obj, list):
        return [mask_dict(v) for v in obj]
    if isinstance(obj, str):
        return mask_text(obj).text
    return obj


# ── Verification helper (used by tests and by the privacy self-check) ─────────

_LEAK_CHECKS: tuple[tuple[str, Pattern[str]], ...] = (
    ("card", _c(r"\b(?:\d[ \-]?){12,18}\d\b")),
    ("email", _c(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("phone", _c(r"(?:\+?91[\-\s]?|\b0)?[6-9](?:\d[\-\s]?){8}\d\b")),
    ("api_key", _c(r"\brzp_(?:live|test)_[A-Za-z0-9]{6,}\b")),
    ("aadhaar", _c(r"\b\d{4}[ \-]?\d{4}[ \-]?\d{4}\b(?!\d)")),
    ("pan", _c(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
)


def contains_unmasked_pii(text: str) -> list[str]:
    """Return the kinds of PII still present. Empty list means clean.

    Used as an assertion in tests and as a runtime guard before anything is
    written to the audit log.
    """
    if not text:
        return []
    found: list[str] = []
    for kind, rx in _LEAK_CHECKS:
        if rx.search(text):
            found.append(kind)
    return found


def assert_clean(text: str, where: str = "") -> None:
    """Raise if `text` still carries PII. Fail loudly rather than leak quietly."""
    leaks = contains_unmasked_pii(text)
    if leaks:
        raise ValueError(
            f"unmasked PII ({', '.join(sorted(set(leaks)))}) reached {where or 'a sink'}"
        )
