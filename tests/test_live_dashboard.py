"""
Live-dashboard safety.

The worst thing this product could do is quote demo figures while the merchant
is looking at their own real account. The numbers would be internally
consistent, correctly formatted, and belong to somebody else.

These tests exist because that is exactly what it did before the guard was
added: on a live dashboard showing ₹47,320, it confidently answered with the
seed's ₹10,000 / ₹9,264 and raised no warning at all.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from merchant.audit import KIND_FALLBACK, AuditLog
from merchant.explain import verify_no_invented_numbers
from merchant.models import DashboardPage, Language, ScreenContext
from merchant.pipeline import MerchantPipeline, PipelineConfig, PipelineDeps
from merchant.privacy import PrivacyState
from merchant.screen_facts import (
    extract_amounts,
    is_live_dashboard,
    settlement_shortfall_from_screen,
)

LIVE_OCR = ("Settlements  Gross amount 47,320  Razorpay fees 946  "
            "Tax on fees 170  Net settlement 46,204  UTR HDFC9931")

# Figures from the demo seed. None of these may appear over a live dashboard.
SEED_FIGURES = ("10,000", "9,264", "736")


def live_screen(ocr: str = LIVE_OCR) -> ScreenContext:
    return ScreenContext(
        ocr_text=ocr,
        url_hint="https://dashboard.razorpay.com/app/settlements",
        window_title="Settlements | Razorpay Dashboard",
        captured=True,
    )


def build() -> MerchantPipeline:
    privacy = PrivacyState()
    privacy.grant_permission()
    return MerchantPipeline(PipelineConfig(), PipelineDeps(privacy=privacy,
                                                           audit=AuditLog()))


def ask(pipe: MerchantPipeline, text: str, screen: ScreenContext):
    return asyncio.run(pipe.ask(text, screen))


# ── Detecting a live dashboard ────────────────────────────────────────────────


@pytest.mark.parametrize("url,title,expected", [
    ("https://dashboard.razorpay.com/app/settlements", "", True),
    ("https://dashboard.razorpay.com/app/payments", "Razorpay Dashboard", True),
    ("", "Settlements | Razorpay Dashboard", True),
    ("http://127.0.0.1:8756/dashboard/", "Merchant Dashboard", False),
    ("http://localhost:8756/dashboard/", "", False),
    ("", "", False),
    ("https://razorpay.com/docs/settlements", "Docs", False),
])
def test_live_dashboard_detection(url: str, title: str, expected: bool) -> None:
    ctx = ScreenContext(url_hint=url, window_title=title, captured=True)
    assert is_live_dashboard(ctx) is expected


def test_local_mock_is_never_treated_as_live() -> None:
    """The demo must keep working — a false positive here breaks it."""
    ctx = ScreenContext(url_hint="http://127.0.0.1:8756/dashboard/index.html",
                        window_title="Merchant Dashboard", captured=True)
    assert is_live_dashboard(ctx) is False


# ── Reading amounts off the screen ────────────────────────────────────────────


def test_amounts_are_extracted_from_screen_text() -> None:
    found = extract_amounts(LIVE_OCR)
    by_key = found.by_key()
    assert by_key["gross_amount"].value_text == "₹47,320"
    assert by_key["fees"].value_text == "₹946"
    assert by_key["tax"].value_text == "₹170"
    assert by_key["net_amount"].value_text == "₹46,204"
    assert all(f.source == "ocr" for f in found.facts)


def test_shortfall_is_computed_from_screen_values() -> None:
    found = extract_amounts(LIVE_OCR)
    shortfall = settlement_shortfall_from_screen(found)
    assert shortfall is not None
    assert shortfall.value_text == "₹1,116"  # 47,320 − 46,204


def test_missing_labels_are_skipped_not_guessed() -> None:
    found = extract_amounts("Settlements  Net settlement 46,204  UTR HDFC9931")
    by_key = found.by_key()
    assert "net_amount" in by_key
    assert "gross_amount" not in by_key
    assert "fees" not in by_key
    assert settlement_shortfall_from_screen(found) is None


def test_unreadable_text_yields_nothing() -> None:
    assert extract_amounts("").facts == []
    assert extract_amounts("no amounts here at all").facts == []


# ── The guarantee ─────────────────────────────────────────────────────────────


def test_demo_figures_never_appear_over_a_live_dashboard() -> None:
    pipe = build()
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?", live_screen())

    for figure in SEED_FIGURES:
        assert figure not in r.answer, (
            f"demo figure {figure!r} quoted over a live dashboard: {r.answer}"
        )
    assert "47,320" in r.answer and "46,204" in r.answer
    assert all(f.source in ("ocr", "computed") for f in r.facts_used)
    assert verify_no_invented_numbers(r.answer, r.facts_used) == []


def test_live_answer_says_where_its_numbers_came_from() -> None:
    pipe = build()
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?", live_screen())
    assert "screen" in r.answer.lower()
    assert r.uncertainty, "must flag that these were read off the screen"


def test_live_dashboard_with_unreadable_amounts_refuses_rather_than_guesses() -> None:
    """No legible numbers means no numbers — not a fall back to demo data."""
    pipe = build()
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?",
            live_screen("Settlements  UTR HDFC9931  Status Processed"))

    assert not re.search(r"₹\s?\d", r.answer), f"invented a figure: {r.answer}"
    for figure in SEED_FIGURES:
        assert figure not in r.answer
    assert r.fallback_used is True
    assert r.confidence <= 0.4
    assert pipe.deps.audit.events(kind=KIND_FALLBACK), "refusal must be audited"


def test_live_dashboard_still_highlights_the_right_rows() -> None:
    pipe = build()
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?", live_screen())
    ids = {t.target_id for t in r.highlight_targets}
    assert {"settlement.gross_amount", "settlement.fees", "settlement.tax",
            "settlement.net_amount"} <= ids
    assert r.page is DashboardPage.SETTLEMENTS
    for target in r.highlight_targets:
        assert target.rect is None, "server side must not emit coordinates"


def test_partial_screen_data_is_used_honestly() -> None:
    """Gross and net legible but not the fee lines: explain what we can."""
    pipe = build()
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?",
            live_screen("Settlements  Gross amount 47,320  Net settlement 46,204"))
    assert "47,320" in r.answer and "46,204" in r.answer
    assert "1,116" in r.answer
    assert r.warnings, "must say the fee breakdown could not be read"
    assert verify_no_invented_numbers(r.answer, r.facts_used) == []


@pytest.mark.parametrize("utterance,language", [
    ("Mere payment ka settlement kam kyon aaya?", Language.HINGLISH),
    ("मेरा सेटलमेंट कम क्यों आया?", Language.HINDI),
    ("Why is my settlement lower than what I collected?", Language.ENGLISH),
])
def test_live_flow_works_in_every_language(utterance: str,
                                           language: Language) -> None:
    pipe = build()
    r = ask(pipe, utterance, live_screen())
    assert r.language is language
    assert "47,320" in r.answer
    for figure in SEED_FIGURES:
        assert figure not in r.answer


def test_demo_dashboard_still_uses_demo_data() -> None:
    """The guard must not break the demo it was added to protect."""
    pipe = build()
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?",
            ScreenContext(url_hint="http://127.0.0.1:8756/dashboard/",
                          window_title="Merchant Dashboard", captured=True))
    assert "₹9,264" in r.answer
    assert "47,320" not in r.answer
