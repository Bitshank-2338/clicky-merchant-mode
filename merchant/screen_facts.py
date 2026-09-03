"""
Reading numbers off the screen itself.

Merchant Mode's adapters are the right source of truth when the merchant is
looking at a dashboard that adapter actually serves. On the **live** Razorpay
dashboard they are not: the adapter would happily supply demo figures while the
merchant is staring at their own real ones.

That is the worst failure this product could have — confidently correct-looking
numbers that belong to somebody else's account. So when the screen is a real
Razorpay dashboard, the numbers come from the screen or they do not come at all.

This module extracts labelled currency amounts out of OCR text. It is
deliberately conservative: a label it does not recognise, or a number it cannot
parse cleanly, is skipped rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from merchant.models import Fact, Money, ScreenContext

# Hosts that mean "this is the merchant's real account, not our demo".
_LIVE_HOST = re.compile(r"\bdashboard\.razorpay\.com\b", re.IGNORECASE)

# Our own mock dashboard, which is served locally.
_DEMO_HOST = re.compile(r"\b(127\.0\.0\.1|localhost)\b", re.IGNORECASE)

_LIVE_TITLE = re.compile(r"razorpay\s+dashboard", re.IGNORECASE)
_DEMO_TITLE = re.compile(r"\bdemo\b|\bmerchant dashboard\b", re.IGNORECASE)


def is_live_dashboard(ctx: ScreenContext) -> bool:
    """True when the screen appears to be a real Razorpay account.

    Errs toward `True` only on positive evidence — an unrecognised screen is
    not treated as live, because that would needlessly block the demo.
    """
    url = ctx.url_hint or ""
    title = ctx.window_title or ""

    if _DEMO_HOST.search(url) or _DEMO_TITLE.search(title):
        return False
    if _LIVE_HOST.search(url):
        return True
    if _LIVE_TITLE.search(title):
        return True
    return False


# ── Amount parsing ────────────────────────────────────────────────────────────

# "₹1,23,456.78", "Rs 1,234", "1,23,456" — the symbol is optional because OCR
# frequently drops or mangles "₹".
_AMOUNT = r"(?:₹|Rs\.?|INR)?\s*(\d[\d,]*(?:\.\d{1,2})?)"

# Label → the fact key `merchant.facts` uses, so downstream code is unchanged.
_LABELS: list[tuple[str, str]] = [
    ("net settlement", "net_amount"),
    ("net amount", "net_amount"),
    ("gross amount", "gross_amount"),
    ("gross collection", "gross_amount"),
    ("razorpay fees", "fees"),
    ("razorpay fee", "fees"),
    ("tax on fees", "tax"),
    ("tax on fee", "tax"),
    ("adjustments", "adjustments"),
    ("adjustment", "adjustments"),
    ("refunds", "refunds"),
    ("disputes", "disputes"),
    ("fees", "fees"),
    ("tax", "tax"),
]

_DISPLAY = {
    "gross_amount": "Gross amount",
    "fees": "Razorpay fees",
    "tax": "Tax on fees",
    "refunds": "Refunds",
    "adjustments": "Adjustments",
    "disputes": "Disputes",
    "net_amount": "Net settlement",
}


def _parse_amount(raw: str) -> Optional[Money]:
    """'1,23,456.78' → Money. Returns None on anything ambiguous."""
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Money.from_rupees(cleaned)
    except (ValueError, ArithmeticError):
        return None


@dataclass
class ScreenFacts:
    """Amounts read directly off the merchant's screen."""

    facts: list[Fact] = field(default_factory=list)
    found_keys: set[str] = field(default_factory=set)
    unreadable: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return bool(self.facts)

    def by_key(self) -> dict[str, Fact]:
        return {f.key: f for f in self.facts}


def extract_amounts(ocr_text: str) -> ScreenFacts:
    """Pull labelled currency amounts out of screen text.

    Only labels in `_LABELS` are recognised, and each key is taken once — the
    first, which on a settlement breakdown is the row itself rather than a
    later summary repeat.
    """
    out = ScreenFacts()
    if not ocr_text or not ocr_text.strip():
        return out

    text = ocr_text.replace(" ", " ")

    for label, key in _LABELS:
        if key in out.found_keys:
            continue
        # The amount may sit on the same line or wrap to the next one, so allow
        # a little whitespace — but not so much that we grab an unrelated row.
        pattern = re.compile(
            rf"{re.escape(label)}\s*[:\-]?\s*{_AMOUNT}",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            continue
        money = _parse_amount(match.group(1))
        if money is None:
            out.unreadable.append(label)
            continue
        out.found_keys.add(key)
        out.facts.append(
            Fact(
                key=key,
                label=_DISPLAY.get(key, label.title()),
                value_text=money.format(),
                source="ocr",
                raw_value=money.rupees,
            )
        )

    return out


def settlement_shortfall_from_screen(facts: ScreenFacts) -> Optional[Fact]:
    """Gross minus net, when both were legible. Otherwise nothing."""
    by_key = facts.by_key()
    gross, net = by_key.get("gross_amount"), by_key.get("net_amount")
    if gross is None or net is None:
        return None
    if gross.raw_value is None or net.raw_value is None:
        return None
    shortfall = Money.from_rupees(abs(gross.raw_value - net.raw_value))
    return Fact(
        key="shortfall",
        label="Total deducted from gross",
        value_text=shortfall.format(),
        source="computed",
        raw_value=shortfall.rupees,
    )


LIVE_WITHOUT_SCREEN_DATA = {
    "english": (
        "This looks like your real Razorpay dashboard, so I will not use my demo "
        "figures here. I could not read the amounts off this screen clearly — "
        "please tell me which number you are asking about, or switch on screen "
        "reading so I can see it properly."
    ),
    "hindi": (
        "यह आपका असली Razorpay डैशबोर्ड लग रहा है, इसलिए मैं अपने डेमो के आँकड़े "
        "यहाँ इस्तेमाल नहीं करूँगी। इस स्क्रीन से रकम साफ़ नहीं पढ़ पाई — कृपया बताइए "
        "आप किस आँकड़े के बारे में पूछ रहे हैं।"
    ),
    "hinglish": (
        "Ye aapka asli Razorpay dashboard lag raha hai, isliye main apne demo ke "
        "numbers yahan use nahi karungi. Is screen se amount saaf nahi padh payi — "
        "please bataiye aap kis number ke baare mein pooch rahe hain."
    ),
}

LIVE_DATA_NOTICE = {
    "english": "These figures are read from your screen, not from demo data.",
    "hindi": "ये आँकड़े आपकी स्क्रीन से पढ़े गए हैं, डेमो डेटा से नहीं।",
    "hinglish": "Ye numbers aapki screen se padhe gaye hain, demo data se nahi.",
}
