"""
End-to-end pipeline tests: question in, structured response out.

These cover the required demo flows, the three languages, the fallback paths
and — most importantly — the guarantee that no rupee figure appears in an
answer unless it was computed from adapter data.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import pytest

from merchant.audit import KIND_ACTION_BLOCKED, KIND_FALLBACK, AuditLog
from merchant.explain import verify_no_invented_numbers
from merchant.masking import contains_unmasked_pii
from merchant.models import (
    AdapterMode,
    DashboardPage,
    Intent,
    Language,
    ScreenContext,
)
from merchant.pipeline import MerchantPipeline, PipelineConfig, PipelineDeps
from merchant.privacy import PrivacyState


def build(scenario: str = "settlement_lower_than_gross",
          refine=None,
          require_permission: bool = True,
          granted: bool = True) -> MerchantPipeline:
    privacy = PrivacyState()
    if granted:
        privacy.grant_permission()
    deps = PipelineDeps(privacy=privacy, audit=AuditLog(), refine=refine)
    return MerchantPipeline(
        PipelineConfig(scenario_id=scenario, require_permission=require_permission),
        deps,
    )


def ask(pipe: MerchantPipeline, text: str, screen: Optional[ScreenContext] = None):
    return asyncio.run(pipe.ask(text, screen))


def screen_for(*target_ids: str, title: str = "") -> ScreenContext:
    return ScreenContext(
        dom_map={t: (10, 10, 100, 20) for t in target_ids},
        window_title=title,
        captured=True,
    )


# ── Demo flow 1: settlement shortfall ─────────────────────────────────────────


@pytest.mark.parametrize("utterance,language", [
    ("Mere payment ka settlement kam kyon aaya?", Language.HINGLISH),
    ("मेरा सेटलमेंट कम क्यों आया?", Language.HINDI),
    ("Why is my settlement lower than what I collected?", Language.ENGLISH),
])
def test_settlement_shortfall_in_every_language(utterance: str, language: Language) -> None:
    pipe = build()
    r = ask(pipe, utterance, screen_for("settlement.gross_amount"))

    assert r.intent is Intent.EXPLAIN_SETTLEMENT
    assert r.page is DashboardPage.SETTLEMENTS
    assert r.language is language

    # The exact arithmetic from the brief: 10000 - 200 - 36 - 500 = 9264.
    assert "₹10,000" in r.answer
    assert "₹9,264" in r.answer
    assert "₹200" in r.answer
    assert "₹36" in r.answer
    assert "₹500" in r.answer

    fact_keys = {f.key for f in r.facts_used}
    assert {"gross_amount", "fees", "tax", "refunds", "net_amount",
            "computed_net"} <= fact_keys

    target_ids = {t.target_id for t in r.highlight_targets}
    assert {"settlement.gross_amount", "settlement.fees", "settlement.tax",
            "settlement.refunds", "settlement.net_amount"} <= target_ids

    assert verify_no_invented_numbers(r.answer, r.facts_used) == []
    assert r.source_urls, "an explanation must cite the docs it drew on"
    assert r.why_seeing_this and r.what_next


def test_settlement_computed_net_matches_reported_net() -> None:
    pipe = build()
    r = ask(pipe, "settlement kam kyon aaya")
    facts = {f.key: f.value_text for f in r.facts_used}
    assert facts["computed_net"] == facts["net_amount"] == "₹9,264"
    assert facts["shortfall"] == "₹736"


# ── Demo flow 2: failed payments ──────────────────────────────────────────────


def test_failed_payments_flow_gives_steps_and_never_promises_success() -> None:
    pipe = build("multiple_failed_payments")
    r = ask(pipe, "Kal ke failed payments dikhao",
            screen_for("payments.status_filter", title="Payments"))

    assert r.intent is Intent.SHOW_FAILED_PAYMENTS
    assert r.page is DashboardPage.PAYMENTS
    assert len(r.steps) >= 4

    target_ids = [t.target_id for t in r.highlight_targets]
    assert "payments.date_filter" in target_ids
    assert "payments.status_filter" in target_ids
    assert "payments.error_reason" in target_ids

    facts = {f.key: f.value_text for f in r.facts_used}
    assert facts["failed_count"] == "4"
    # 120000 + 89900 + 250000 + 45000 paise = 504900 paise = ₹5,049
    assert facts["failed_total"] == "₹5,049"

    lowered = r.answer.lower()
    for forbidden in ("will succeed", "guaranteed", "definitely work", "always work"):
        assert forbidden not in lowered, f"answer promised success: {forbidden!r}"
    assert any("cannot promise" in w.lower() or "retry" in w.lower() for w in r.warnings)


def test_next_step_walks_the_checklist_and_finishes() -> None:
    pipe = build("multiple_failed_payments")
    first = ask(pipe, "Kal ke failed payments dikhao")
    total = len(first.steps)
    assert total >= 4

    seen = []
    for _ in range(total):
        r = ask(pipe, "next")
        seen.append(r)
    assert all(s.done for s in seen[-1].steps), "every step should end up done"

    beyond = ask(pipe, "next")
    assert beyond.intent is Intent.NEXT_STEP
    assert "finish" in beyond.answer.lower() or "complete" in beyond.answer.lower() \
        or "पूरे" in beyond.answer


# ── Demo flow 3: payment link tutorial ────────────────────────────────────────


def test_payment_link_tutorial_teaches_but_never_creates() -> None:
    pipe = build("payment_link_creation")
    r = ask(pipe, "Mujhe payment link banana sikhao",
            screen_for("link.amount", title="Payment Links"))

    assert r.intent is Intent.CREATE_PAYMENT_LINK_TUTORIAL
    assert r.requires_confirmation is True

    step_targets = [s.target_id for s in r.steps]
    for required in ("link.amount", "link.description", "link.expiry",
                     "link.customer_name", "link.customer_contact",
                     "link.preview", "link.create_button"):
        assert required in step_targets, f"tutorial skips {required}"

    final = r.steps[-1]
    assert final.requires_confirmation is True
    assert any(w for w in r.warnings if "not create" in w.lower() or "not send" in w.lower())


# ── Demo flow 4: refund education ─────────────────────────────────────────────


def test_refund_education_never_claims_a_refund_happened() -> None:
    pipe = build("full_and_partial_refunds")
    r = ask(pipe, "Customer ko refund kaise karte hain?",
            screen_for("refunds.type", title="Refunds"))

    assert r.intent is Intent.REFUND_TUTORIAL
    assert r.requires_confirmation is True
    lowered = r.answer.lower()
    for forbidden in ("refund issued", "refund processed successfully",
                      "i have refunded", "refund complete"):
        assert forbidden not in lowered
    assert r.steps and r.steps[-1].requires_confirmation is True


@pytest.mark.parametrize("demand,expected_intent", [
    ("Refund kar do abhi", Intent.REFUND_TUTORIAL),
    ("payment link bana do aur bhej do", Intent.CREATE_PAYMENT_LINK_TUTORIAL),
])
def test_direct_action_demands_are_refused_and_audited(
    demand: str, expected_intent: Intent
) -> None:
    pipe = build()
    r = ask(pipe, demand)

    assert r.requires_confirmation is True
    assert r.intent is expected_intent
    assert any("read-only" in w.lower() for w in r.warnings)
    assert r.steps, "a refusal should still teach the merchant how to do it"
    assert pipe.deps.audit.events(kind=KIND_ACTION_BLOCKED), "refusal must be audited"


# ── Demo flow 5: explain this screen ──────────────────────────────────────────


def test_explain_screen_on_settlements() -> None:
    pipe = build()
    r = ask(pipe, "Is screen ko mujhe simple language mein samjhao",
            screen_for("settlement.gross_amount", "settlement.net_amount"))
    assert r.intent is Intent.EXPLAIN_SCREEN
    assert r.page is DashboardPage.SETTLEMENTS
    assert "Gross" in r.answer or "gross" in r.answer.lower()
    assert verify_no_invented_numbers(r.answer, r.facts_used) == []


def test_explain_screen_never_silently_pretends_it_read_the_screen() -> None:
    """With no readable screen, Demo Mode may describe the loaded demo page —
    but only while saying plainly that it did not read the screen."""
    pipe = build()
    r = ask(pipe, "explain this screen to me simply", ScreenContext(captured=True))
    assert r.uncertainty, "must flag that the page was not read from the screen"
    assert any("could not read" in u.lower() for u in r.uncertainty)
    assert r.confidence <= 0.6


def test_explain_screen_admits_unknown_when_there_is_no_demo_page() -> None:
    """Outside Demo Mode there is no scenario to fall back on, so the honest
    answer is that the page was not recognised."""
    from merchant.adapters.base import DashboardAdapter, DataResult
    from merchant.models import AdapterMode

    class BlankAdapter(DashboardAdapter):
        mode = AdapterMode.RAZORPAY_TEST

        def health(self) -> bool:
            return True

        def settlements(self, limit: int = 10) -> DataResult:
            return DataResult(ok=True, rows=[], source="test")

        def payments(self, limit: int = 25, status=None) -> DataResult:
            return DataResult(ok=True, rows=[], source="test")

        def refunds(self, limit: int = 25) -> DataResult:
            return DataResult(ok=True, rows=[], source="test")

        def payment_links(self, limit: int = 25) -> DataResult:
            return DataResult(ok=True, rows=[], source="test")

    privacy = PrivacyState()
    privacy.grant_permission()
    pipe = MerchantPipeline(
        PipelineConfig(require_permission=True),
        PipelineDeps(privacy=privacy, audit=AuditLog(), adapter=BlankAdapter()),
    )
    r = asyncio.run(pipe.ask("explain this screen to me simply",
                             ScreenContext(captured=True)))
    assert r.page is DashboardPage.UNKNOWN
    assert r.fallback_used is True
    assert r.uncertainty
    assert r.confidence <= 0.3, "an unrecognised page must not be confident"


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_empty_state_does_not_invent_rows() -> None:
    pipe = build("empty_state")
    r = ask(pipe, "settlement kam kyon aaya")
    assert not re.search(r"₹\s?\d", r.answer), f"invented an amount: {r.answer}"
    assert r.facts_used == []


def test_api_failure_says_so_instead_of_guessing() -> None:
    pipe = build("api_failure")
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    assert r.fallback_used is True
    assert r.confidence == 0.0
    assert not re.search(r"₹\s?\d", r.answer)
    assert any("SERVER_ERROR" in w for w in r.warnings)


def test_incomplete_data_flags_the_gap_and_computes_nothing_fake() -> None:
    pipe = build("incomplete_data")
    r = ask(pipe, "settlement kam kyon aaya")

    fact_keys = {f.key for f in r.facts_used}
    assert "fees" not in fact_keys, "a missing fee must not become a fact"
    assert "computed_net" not in fact_keys, "must not compute a net from missing parts"
    assert r.warnings or r.uncertainty
    assert verify_no_invented_numbers(r.answer, r.facts_used) == []


def test_unknown_question_admits_ignorance() -> None:
    pipe = build()
    r = ask(pipe, "What is the weather in Mumbai tomorrow?")
    assert r.intent is Intent.UNKNOWN
    assert r.fallback_used is True
    assert not re.search(r"₹\s?\d", r.answer)


def test_permission_gate_blocks_before_any_data_is_read() -> None:
    pipe = build(granted=False)
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    assert r.requires_confirmation is True
    assert r.facts_used == [], "no data may be read before permission is granted"
    assert not re.search(r"₹\s?\d", r.answer)


def test_caller_cannot_bypass_the_permission_gate_by_claiming_a_capture() -> None:
    """Regression: `captured=True` is caller-supplied and must grant nothing.

    An earlier version treated a caller-provided ScreenContext as proof that
    permission had been given, so any HTTP client could set the flag and read
    account data without consent.
    """
    pipe = build(granted=False)
    forged = ScreenContext(
        dom_map={"settlement.gross_amount": (10, 10, 100, 20)},
        ocr_text="Gross amount 10,000 Net settlement 9,264",
        window_title="Settlements",
        captured=True,
    )
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?", forged)
    assert r.facts_used == [], "account data was read without permission"
    assert not re.search(r"₹\s?\d", r.answer)
    assert r.requires_confirmation is True


def test_stop_monitoring_takes_effect_immediately() -> None:
    pipe = build()
    assert ask(pipe, "settlement kam kyon aaya").facts_used
    pipe.stop_monitoring()
    after = ask(pipe, "settlement kam kyon aaya")
    assert after.facts_used == []
    assert after.requires_confirmation is True


# ── Model fallback behaviour ──────────────────────────────────────────────────


def test_pipeline_works_and_labels_fallback_without_a_model() -> None:
    pipe = build(refine=None)
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    assert r.answer and "₹9,264" in r.answer
    assert r.fallback_used is True, "a template answer must be labelled as fallback"


def test_model_refinement_is_used_when_it_behaves() -> None:
    async def good_refine(system: str, user: str) -> str:
        return ("Aapke customers ne ₹10,000 diye the. Fees ₹200, tax ₹36 aur "
                "refund ₹500 katne ke baad ₹9,264 bank mein aaya.")

    pipe = build(refine=good_refine)
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    assert "bank mein aaya" in r.answer
    assert r.fallback_used is False


def test_model_that_invents_a_number_is_discarded() -> None:
    async def lying_refine(system: str, user: str) -> str:
        return "Aapka settlement ₹99,999 tha aur ₹1,234 fees kati."

    pipe = build(refine=lying_refine)
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")

    assert "99,999" not in r.answer, "invented amount reached the merchant"
    assert "1,234" not in r.answer
    assert "₹9,264" in r.answer, "must fall back to the verified template"
    assert r.fallback_used is True
    assert pipe.deps.audit.events(kind=KIND_FALLBACK)


def test_model_crash_falls_back_cleanly() -> None:
    async def broken_refine(system: str, user: str) -> str:
        raise ConnectionError("ollama is not running")

    pipe = build(refine=broken_refine)
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    assert "₹9,264" in r.answer
    assert r.fallback_used is True


def test_model_returning_junk_falls_back() -> None:
    async def empty_refine(system: str, user: str) -> str:
        return "   "

    pipe = build(refine=empty_refine)
    r = ask(pipe, "settlement kam kyon aaya")
    assert "₹9,264" in r.answer
    assert r.fallback_used is True


# ── Cross-cutting invariants ──────────────────────────────────────────────────


ALL_UTTERANCES = [
    "Mere payment ka settlement kam kyon aaya?",
    "Kal ke failed payments dikhao",
    "Mujhe payment link banana sikhao",
    "Customer ko refund kaise karte hain?",
    "Is screen ko mujhe simple language mein samjhao",
    "Refund aur reversal mein kya difference hai?",
    "मेरा सेटलमेंट कम क्यों आया?",
    "What is the weather in Mumbai?",
    "Refund kar do abhi",
    "settlement report kaise samjhu",
]


@pytest.mark.parametrize("utterance", ALL_UTTERANCES)
def test_no_answer_ever_leaks_pii(utterance: str) -> None:
    pipe = build()
    r = ask(pipe, utterance)
    assert contains_unmasked_pii(r.answer) == [], f"PII leaked answering {utterance!r}"
    for step in r.steps:
        assert contains_unmasked_pii(f"{step.title} {step.why}") == []


@pytest.mark.parametrize("utterance", ALL_UTTERANCES)
def test_no_answer_ever_invents_a_number(utterance: str) -> None:
    pipe = build()
    r = ask(pipe, utterance)
    assert verify_no_invented_numbers(r.answer, r.facts_used) == [], (
        f"invented an amount answering {utterance!r}: {r.answer}"
    )


@pytest.mark.parametrize("utterance", ALL_UTTERANCES)
def test_response_serialises_to_the_documented_contract(utterance: str) -> None:
    pipe = build()
    d = ask(pipe, utterance).to_dict()
    required = {"page", "intent", "language", "answer", "steps", "highlight_targets",
                "facts_used", "confidence", "requires_confirmation", "source_urls",
                "fallback_used"}
    assert required <= set(d)
    assert isinstance(d["confidence"], float)
    assert 0.0 <= d["confidence"] <= 1.0
    assert isinstance(d["requires_confirmation"], bool)
    assert isinstance(d["fallback_used"], bool)
    assert d["adapter_mode"] == AdapterMode.DEMO.value


def test_guard_does_not_flag_ordinary_words_as_currency() -> None:
    """Regression: the currency pattern matched "rs," inside "yours," and
    deleted a correct answer. A false positive here is not harmless."""
    from merchant.models import Fact

    facts = [Fact("failed_total", "Value of failed payments", "₹5,049", "computed",
                  5049.0)]
    answer = ("Status tells you what happened: captured means the money is yours, "
              "failed means it never arrived. Value of failed payments: ₹5,049.")
    assert verify_no_invented_numbers(answer, facts) == []

    # And it must still catch a genuinely invented figure.
    assert verify_no_invented_numbers("Your settlement was ₹99,999.", facts)
    assert verify_no_invented_numbers("We deducted Rs 1,234 in fees.", facts)


def test_explain_screen_on_payments_keeps_its_numbers() -> None:
    pipe = build("multiple_failed_payments")
    r = ask(pipe, "explain this screen to me simply",
            screen_for("payments.status_filter", title="Payments"))
    assert "₹5,049" in r.answer, f"guard stripped a verified figure: {r.answer}"
    assert verify_no_invented_numbers(r.answer, r.facts_used) == []


def test_every_question_and_answer_is_audited() -> None:
    pipe = build()
    ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    kinds = {e.kind for e in pipe.deps.audit.events()}
    assert "question" in kinds and "answer" in kinds


def test_internal_error_does_not_produce_a_money_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = build()

    def boom(row):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr("merchant.pipeline.explain_settlement", boom)
    r = ask(pipe, "Mere payment ka settlement kam kyon aaya?")
    assert not re.search(r"₹\s?\d", r.answer)
    assert r.confidence == 0.0
    assert r.fallback_used is True
