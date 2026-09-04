"""
The Merchant Mode pipeline.

    permission → capture → masking → OCR/UI extraction → page detection →
    intent detection → knowledge retrieval → fact extraction → explanation →
    highlight targets → (voice) → optional confirmed action → audit

This module owns the orchestration and every honesty decision along the way:
when to say "I can't see that", when to refuse, when to fall back, and what
confidence to report. It has no PyQt and no HTTP dependency, so the same code
runs behind the desktop panel, behind the FastAPI sidecar and inside the
evaluation harness — which is what makes the evaluation numbers meaningful.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Sequence

from merchant import explain, kb, locate, screen_facts
from merchant.adapters import get_adapter
from merchant.adapters.base import DashboardAdapter, DataResult
from merchant.audit import (
    KIND_ACTION_BLOCKED,
    KIND_ANSWER,
    KIND_ERROR,
    KIND_FALLBACK,
    KIND_QUESTION,
    KIND_STOP,
    AuditLog,
)
from merchant.confirm import NEVER_AUTOMATED, ConfirmationManager, blocked_action_message
from merchant.facts import (
    explain_settlement,
    settlement_period_facts,
    summarise_failed_payments,
    summarise_refunds,
)
from merchant.intent import detect_intent
from merchant.masking import mask_text
from merchant.models import (
    LOW_CONFIDENCE_THRESHOLD,
    AdapterMode,
    DashboardPage,
    Fact,
    HighlightTarget,
    Intent,
    Language,
    MerchantResponse,
    ScreenContext,
    Severity,
    Step,
)
from merchant.page_detect import detect_page, page_from_id
from merchant.privacy import PrivacyState

# Utterances that mean "just do it for me" rather than "teach me". These route
# to a refusal + teaching flow, never to an action.
#
# Patterns rather than substrings, because Hindi imperatives inflect freely —
# "kar do", "kar de", "kar dijiye", "kardo" are all the same instruction, and a
# fixed substring list silently missed most of them. Under-matching here is a
# safety failure, so the imperative alternation is deliberately generous.
_IMPERATIVE = r"(?:kar\s*(?:do|de|do na|dijiye|dena)|kardo|karde|kr\s*do)"

_ACTION_DEMANDS: dict[str, tuple[re.Pattern[str], ...]] = {
    "issue_refund": (
        re.compile(rf"\brefund\b.{{0,40}}{_IMPERATIVE}", re.I),
        re.compile(rf"{_IMPERATIVE}.{{0,25}}\brefund\b", re.I),
        re.compile(r"\b(refund it|do the refund|issue (?:a |the )?refund|"
                   r"process (?:a |the )?refund|just refund)\b", re.I),
        re.compile(rf"paisa\s*wapas.{{0,25}}{_IMPERATIVE}", re.I),
        re.compile(r"रिफंड.{0,25}(कर\s*दो|कर\s*दीजिए|कीजिए)", re.I),
    ),
    "send_payment_link": (
        re.compile(r"\blink\b.{0,30}(bhej\s*(?:do|de|dijiye)|bhejo|bhej\s*dena)", re.I),
        re.compile(r"\b(send (?:the |this |a )?link|send it to (?:him|her|them|the customer))\b",
                   re.I),
        re.compile(r"लिंक.{0,25}भेज\s*(?:दो|दीजिए)", re.I),
    ),
    "create_payment_link": (
        re.compile(rf"\blink\b.{{0,30}}(?:bana\s*(?:do|de|dijiye)|banado|{_IMPERATIVE})",
                   re.I),
        re.compile(r"\b(create (?:it|the link) for me|make (?:me )?(?:the|a) link)\b", re.I),
        re.compile(r"लिंक.{0,25}बना\s*(?:दो|दीजिए)", re.I),
    ),
    "message_customer": (
        re.compile(r"\bcustomer\s*ko\b.{0,25}(message|bol|bata)\s*(?:do|de|dijiye)?", re.I),
        re.compile(r"\bmessage the customer\b", re.I),
    ),
}


@dataclass
class PipelineConfig:
    adapter_mode: str = "demo"
    scenario_id: Optional[str] = None
    allow_model_refinement: bool = True
    require_permission: bool = True


@dataclass
class PipelineDeps:
    """Injected collaborators. Every one has a working no-op default."""

    privacy: PrivacyState = field(default_factory=PrivacyState)
    audit: AuditLog = field(default_factory=AuditLog)
    confirmations: Optional[ConfirmationManager] = None
    adapter: Optional[DashboardAdapter] = None
    # Optional async hook: (system_prompt, user_prompt) -> str. Absent means
    # "no model available", which is a fully supported configuration.
    refine: Optional[Callable[[str, str], Awaitable[str]]] = None

    def __post_init__(self) -> None:
        if self.confirmations is None:
            self.confirmations = ConfirmationManager(self.audit)


@dataclass
class GuideState:
    """Progress through a Guide Me checklist."""

    intent: Intent = Intent.UNKNOWN
    steps: list[Step] = field(default_factory=list)
    cursor: int = 0

    @property
    def active(self) -> bool:
        return bool(self.steps) and self.cursor < len(self.steps)

    def current(self) -> Optional[Step]:
        return self.steps[self.cursor] if self.active else None

    def advance(self) -> Optional[Step]:
        if self.cursor < len(self.steps):
            self.steps[self.cursor].done = True
            self.cursor += 1
        return self.current()

    def reset(self, intent: Intent, steps: list[Step]) -> None:
        self.intent = intent
        self.steps = steps
        self.cursor = 0


class MerchantPipeline:
    """Stateful per-session orchestrator. Not thread-safe by design — one
    session, one pipeline, driven from a single event loop."""

    def __init__(self, config: Optional[PipelineConfig] = None,
                 deps: Optional[PipelineDeps] = None):
        self.config = config or PipelineConfig()
        self.deps = deps or PipelineDeps()
        self.guide = GuideState()
        self._adapter = self.deps.adapter or get_adapter(
            self.config.adapter_mode, self.config.scenario_id
        )

    # ── Adapter management ───────────────────────────────────────────────────

    @property
    def adapter(self) -> DashboardAdapter:
        return self._adapter

    def set_scenario(self, scenario_id: str) -> None:
        self._adapter = get_adapter(self.config.adapter_mode, scenario_id)
        self.config.scenario_id = scenario_id
        self.guide = GuideState()

    def stop_monitoring(self) -> None:
        self.deps.privacy.stop_monitoring()
        self.deps.audit.record(KIND_STOP, "merchant stopped screen monitoring",
                               outcome="stopped")

    # ── Main entry point ─────────────────────────────────────────────────────

    async def ask(self, utterance: str, screen: Optional[ScreenContext] = None
                  ) -> MerchantResponse:
        """Answer one merchant question. Never raises for ordinary failures."""
        safe_utterance = mask_text(utterance or "").text
        self.deps.audit.record(KIND_QUESTION, safe_utterance)

        screen = screen or ScreenContext()
        detection = detect_intent(utterance or "")
        language = detection.language
        page_result = detect_page(screen)

        response = MerchantResponse(
            page=page_result.page,
            intent=detection.intent,
            language=language,
            adapter_mode=self._adapter.mode,
        )
        # Sentinel: "no handler has decided a confidence yet". Handlers that
        # know better than the generic formula (a data-source failure is 0.0,
        # a refusal is near-certain) set it themselves and are not overwritten.
        response.confidence = -1.0

        # 1. Permission gate — before anything reads the screen or the account.
        #
        # This used to also pass when `screen.captured` was true, on the theory
        # that a caller holding a screenshot must already have had permission.
        # That was wrong: `captured` is caller-supplied, so any HTTP client
        # could set it and walk straight past the gate. Consent is tracked in
        # exactly one place — PrivacyState — and nothing the caller says can
        # substitute for it.
        if self.config.require_permission and not self.deps.privacy.capture_allowed:
            return self._permission_needed(response, language)

        # 2. "Just do it for me" demands are refused before anything else.
        demanded = _detect_action_demand(utterance or "")
        if demanded:
            return self._refuse_action(response, demanded, utterance or "", language)

        # 3. Guide-me progression.
        if detection.intent is Intent.NEXT_STEP:
            return self._next_step_response(response, language)

        # 4. Route by intent.
        try:
            if detection.intent is Intent.EXPLAIN_SETTLEMENT:
                self._settlement(response, language, screen)
            elif detection.intent in (Intent.SHOW_FAILED_PAYMENTS,
                                      Intent.EXPLAIN_FAILED_PAYMENT):
                self._failed_payments(response, language)
            elif detection.intent is Intent.CREATE_PAYMENT_LINK_TUTORIAL:
                self._payment_link(response, language)
            elif detection.intent is Intent.REFUND_TUTORIAL:
                self._refund(response, language)
            elif detection.intent is Intent.LOCATE_ELEMENT:
                self._locate(response, utterance or "", language)
            elif detection.intent is Intent.EXPLAIN_SCREEN:
                self._explain_screen(response, screen, page_result.page, language)
            elif detection.intent in (Intent.EXPLAIN_FEES, Intent.EXPLAIN_REPORT,
                                      Intent.EXPLAIN_TERM):
                self._knowledge_only(response, utterance or "", detection.topic_hint,
                                     language)
            else:
                self._unknown(response, utterance or "", detection.topic_hint, language)
        except Exception as exc:  # a bug must not become a wrong money answer
            self.deps.audit.record(KIND_ERROR, f"{type(exc).__name__}: {exc}",
                                   outcome="error")
            response.answer = explain.phrases(language).unknown
            response.confidence = 0.0
            response.fallback_used = True
            response.warnings.append("Something went wrong on my side, so I stopped "
                                     "rather than guess.")
            return response

        # 5. Confidence: the weakest link in the chain, not the strongest.
        if response.confidence < 0.0:
            response.confidence = round(
                min(detection.confidence,
                    max(page_result.confidence, 0.5) if response.facts_used
                    else page_result.confidence or detection.confidence),
                3,
            )
        if response.confidence < LOW_CONFIDENCE_THRESHOLD:
            response.uncertainty.append(
                "I am not fully sure I read this screen correctly — please check the "
                "numbers on your dashboard before acting on this."
            )

        # 6. Optional model refinement, guarded.
        if self.config.allow_model_refinement and self.deps.refine and response.answer:
            await self._maybe_refine(response, language)
        else:
            response.fallback_used = response.fallback_used or self.deps.refine is None

        # 7. Final guard — nothing quotes a number we did not compute.
        invented = explain.verify_no_invented_numbers(response.answer, response.facts_used)
        if invented:
            self.deps.audit.record(
                KIND_FALLBACK, f"blocked invented amounts: {', '.join(invented[:3])}",
                outcome="blocked")
            response.answer = explain.phrases(language).cannot_see
            response.confidence = min(response.confidence, 0.2)
            response.fallback_used = True
            response.warnings.append("I could not verify some numbers, so I removed them.")

        self.deps.audit.record(KIND_ANSWER, response.answer, outcome="answered")
        return response

    # ── Intent handlers ──────────────────────────────────────────────────────

    def _settlement(self, r: MerchantResponse, language: Language,
                    screen: Optional[ScreenContext] = None) -> None:
        # On the merchant's real dashboard, adapter data belongs to a different
        # account than the one on screen. Quoting it would be the single worst
        # thing this product could do, so the screen becomes the only source.
        if screen is not None and screen_facts.is_live_dashboard(screen):
            self._settlement_from_screen(r, screen, language)
            return

        result = self._adapter.settlements(limit=5)
        if not self._data_ok(r, result, language):
            return

        row = result.rows[0]
        breakdown = explain_settlement(row)
        r.facts_used = list(breakdown.facts) + settlement_period_facts(row)
        r.answer = explain.settlement_answer(breakdown, language)
        r.highlight_targets = explain.settlement_targets(breakdown)
        r.page = DashboardPage.SETTLEMENTS
        r.warnings.extend(breakdown.warnings)
        if not breakdown.complete:
            r.uncertainty.append(explain.phrases(language).incomplete)

        entries = kb.retrieve("settlement fees tax deduction",
                              DashboardPage.SETTLEMENTS, Intent.EXPLAIN_SETTLEMENT,
                              "settlements", limit=2)
        r.source_urls = kb.source_urls(entries)
        r.why_seeing_this = (
            "Razorpay does not send the full amount customers paid — its fee, the tax on "
            "that fee, and any refunds come out first."
            if language is Language.ENGLISH else
            "Razorpay पूरी रकम नहीं भेजता — पहले उसकी फीस, फीस पर टैक्स और रिफंड कटते हैं।"
            if language is Language.HINDI else
            "Razorpay poori rakam nahi bhejta — pehle uski fees, fees par tax aur refunds katte hain."
        )
        r.what_next = (
            "Open the settlement report if you want this same breakdown for every payment."
            if language is Language.ENGLISH else
            "अगर हर पेमेंट का यही ब्यौरा चाहिए तो सेटलमेंट रिपोर्ट खोलें।"
            if language is Language.HINDI else
            "Agar har payment ka yahi breakdown chahiye to settlement report kholiye."
        )

    def _settlement_from_screen(self, r: MerchantResponse, screen: ScreenContext,
                                language: Language) -> None:
        """Explain a settlement using only amounts read off the live screen."""
        r.page = DashboardPage.SETTLEMENTS
        r.highlight_targets = explain.settlement_targets_all()
        r.source_urls = kb.source_urls(
            kb.retrieve("settlement fees tax deduction", DashboardPage.SETTLEMENTS,
                        Intent.EXPLAIN_SETTLEMENT, "settlements", limit=2)
        )

        found = screen_facts.extract_amounts(screen.ocr_text)
        by_key = found.by_key()

        if "gross_amount" not in by_key or "net_amount" not in by_key:
            r.answer = screen_facts.LIVE_WITHOUT_SCREEN_DATA[language.value]
            r.facts_used = list(found.facts)
            r.confidence = 0.3
            r.fallback_used = True
            r.uncertainty.append(
                "I did not use demo data because this is your real dashboard."
            )
            self.deps.audit.record(
                KIND_FALLBACK,
                "live dashboard detected — refused to quote demo figures",
                outcome="blocked",
            )
            return

        shortfall = screen_facts.settlement_shortfall_from_screen(found)
        facts = list(found.facts) + ([shortfall] if shortfall else [])
        r.facts_used = facts

        deductions = [by_key[k] for k in ("fees", "tax", "refunds", "disputes")
                      if k in by_key]
        parts = [
            _screen_intro(language, by_key["gross_amount"].value_text,
                          by_key["net_amount"].value_text, deductions),
            screen_facts.LIVE_DATA_NOTICE[language.value],
        ]
        if shortfall is not None:
            parts.insert(1, explain.phrases(language).settlement_close.format(
                shortfall=shortfall.value_text))
        r.answer = " ".join(parts)
        r.confidence = 0.7
        r.uncertainty.append(
            "I read these numbers off your screen, so please double-check them "
            "against the dashboard before acting."
        )
        if not deductions:
            r.warnings.append(
                "I could not read the fee and tax lines on this screen, so this "
                "is only the difference between gross and net."
            )

    def _failed_payments(self, r: MerchantResponse, language: Language) -> None:
        result = self._adapter.failed_payments(limit=25)
        if not self._data_ok(r, result, language):
            return

        summary = summarise_failed_payments(result.rows)
        r.facts_used = list(summary.facts)
        r.answer = explain.failed_payments_answer(summary, language)
        r.highlight_targets = explain.failed_payment_targets()
        r.page = DashboardPage.PAYMENTS

        steps = explain.failed_payment_steps(language)
        self.guide.reset(Intent.SHOW_FAILED_PAYMENTS, steps)
        r.steps = steps

        entries = kb.retrieve("failed payment reason", DashboardPage.PAYMENTS,
                              Intent.SHOW_FAILED_PAYMENTS, "failed_payments", limit=2)
        r.source_urls = kb.source_urls(entries)
        r.why_seeing_this = (
            "A failed payment is an attempt that never became money in your account."
            if language is Language.ENGLISH else
            "फेल पेमेंट वह कोशिश है जो कभी आपके खाते में पैसा नहीं बनी।"
            if language is Language.HINDI else
            "Failed payment wo koshish hai jo kabhi aapke account mein paisa bani hi nahi."
        )
        r.what_next = steps[0].title if steps else ""
        r.warnings.append(
            "I cannot promise a retry will succeed — that depends on the customer's bank."
        )

    def _payment_link(self, r: MerchantResponse, language: Language) -> None:
        entries = kb.retrieve("payment link create amount expiry",
                              DashboardPage.PAYMENT_LINKS,
                              Intent.CREATE_PAYMENT_LINK_TUTORIAL, "payment_links",
                              limit=2)
        p = explain.phrases(language)
        r.answer = " ".join(x for x in (p.link_intro, explain.kb_answer(entries, language,
                                                                   fallback_unknown=False))
                            if x)
        steps = explain.payment_link_steps(language)
        self.guide.reset(Intent.CREATE_PAYMENT_LINK_TUTORIAL, steps)
        r.steps = steps
        r.highlight_targets = explain.payment_link_targets()
        r.page = DashboardPage.PAYMENT_LINKS
        r.source_urls = kb.source_urls(entries)
        r.requires_confirmation = True
        r.why_seeing_this = (
            "A payment link asks a real person for real money, so every field matters."
            if language is Language.ENGLISH else
            "पेमेंट लिंक किसी असली व्यक्ति से असली पैसे माँगता है, इसलिए हर खाना ज़रूरी है।"
            if language is Language.HINDI else
            "Payment link kisi asli insaan se asli paisa maangta hai, isliye har field zaroori hai."
        )
        r.what_next = steps[0].title if steps else ""
        r.warnings.append(
            "I will walk you through the form, but I will not create or send a link myself."
        )

    def _refund(self, r: MerchantResponse, language: Language) -> None:
        result = self._adapter.refunds(limit=25)
        entries = kb.retrieve("refund full partial timeline",
                              DashboardPage.REFUNDS, Intent.REFUND_TUTORIAL,
                              "refunds", limit=2)
        p = explain.phrases(language)
        parts = [p.refund_intro, explain.kb_answer(entries, language, fallback_unknown=False)]

        if result.ok and result.rows:
            summary = summarise_refunds(result.rows)
            r.facts_used = list(summary.facts)
            parts.append(
                f"On this screen there are {summary.full_count} full and "
                f"{summary.partial_count} partial refunds."
                if language is Language.ENGLISH else
                f"इस स्क्रीन पर {summary.full_count} पूरे और {summary.partial_count} आंशिक रिफंड हैं।"
                if language is Language.HINDI else
                f"Is screen par {summary.full_count} full aur {summary.partial_count} partial refunds hain."
            )

        r.answer = " ".join(x for x in parts if x)
        steps = explain.refund_steps(language)
        self.guide.reset(Intent.REFUND_TUTORIAL, steps)
        r.steps = steps
        r.highlight_targets = explain.refund_targets()
        r.page = DashboardPage.REFUNDS
        r.source_urls = kb.source_urls(entries)
        r.requires_confirmation = True
        r.why_seeing_this = (
            "A refund moves money out of your account and cannot be undone."
            if language is Language.ENGLISH else
            "रिफंड आपके खाते से पैसा निकालता है और वापस नहीं लिया जा सकता।"
            if language is Language.HINDI else
            "Refund aapke account se paisa nikalta hai aur wapas nahi liya ja sakta."
        )
        r.what_next = steps[0].title if steps else ""
        r.warnings.append(
            "I never issue a refund myself. You confirm it in the dashboard."
        )

    def _explain_screen(self, r: MerchantResponse, screen: ScreenContext,
                        page: DashboardPage, language: Language) -> None:
        p = explain.phrases(language)

        # In Demo Mode the adapter *is* the dashboard, so the active scenario's
        # page is a real signal rather than a guess — worth using when the
        # screen itself could not be read (no OCR, no published layout). The
        # source is recorded so the answer never implies we read the screen.
        if page is DashboardPage.UNKNOWN and self._adapter.mode is AdapterMode.DEMO:
            scenario_page = page_from_id(getattr(self._adapter, "scenario_page", ""))
            if scenario_page is not DashboardPage.UNKNOWN:
                page = scenario_page
                r.confidence = 0.6
                r.uncertainty.append(
                    "I could not read this from your screen — I am describing the "
                    "demo page that is currently loaded."
                )

        r.page = page

        if page is DashboardPage.UNKNOWN:
            r.answer = (
                f"{p.cannot_see} I could not tell which dashboard page this is."
                if language is Language.ENGLISH else
                f"{p.cannot_see} मैं पहचान नहीं पाई कि यह कौन-सा पेज है।"
                if language is Language.HINDI else
                f"{p.cannot_see} Main pehchan nahi payi ki ye kaun sa page hai."
            )
            r.uncertainty.append("Page not recognised.")
            r.fallback_used = True
            # Not knowing which page this is *is* the answer, and it must not be
            # reported with the high confidence the intent match alone earns.
            r.confidence = 0.2
            return

        facts: list[Fact] = []
        if page is DashboardPage.SETTLEMENTS:
            result = self._adapter.settlements(limit=1)
            if result.ok and result.rows:
                row = result.rows[0]
                bd = explain_settlement(row)
                # Explaining a *screen* means covering the whole screen, not
                # just the money rows: the period and UTR are exactly the bits
                # a first-time merchant does not recognise.
                facts = list(bd.facts) + settlement_period_facts(row)
                r.warnings.extend(bd.warnings)
                r.highlight_targets = (explain.settlement_targets(bd)
                                       + explain.topic_targets("settlements"))
                seen: set[str] = set()
                r.highlight_targets = [
                    t for t in r.highlight_targets
                    if not (t.target_id in seen or seen.add(t.target_id))
                ]
        elif page is DashboardPage.PAYMENTS:
            result = self._adapter.payments(limit=25)
            if result.ok:
                facts = list(summarise_failed_payments(result.rows).facts)
                r.highlight_targets = explain.failed_payment_targets()[:3]
        elif page is DashboardPage.REFUNDS:
            result = self._adapter.refunds(limit=25)
            r.highlight_targets = explain.topic_targets("refunds")
            if result.ok and result.rows:
                facts = list(summarise_refunds(result.rows).facts)
        elif page is DashboardPage.REPORTS:
            r.highlight_targets = explain.reports_targets()
        elif page is DashboardPage.PAYMENT_LINKS:
            r.highlight_targets = explain.topic_targets("payment_links")

        r.facts_used = facts
        r.answer = explain.screen_answer(page, language, facts)
        if screen.is_empty() and not facts:
            r.answer = f"{r.answer} {p.no_data}"
            r.uncertainty.append("No readable data on screen.")

        entries = kb.retrieve(page.value, page, Intent.EXPLAIN_SCREEN, "", limit=2)
        r.source_urls = kb.source_urls(entries)
        r.why_seeing_this = explain.screen_answer(page, language)[:200]
        r.what_next = (
            "Ask me about any number you see and I will point at it."
            if language is Language.ENGLISH else
            "जो भी आँकड़ा दिखे, मुझसे पूछिए — मैं उस पर इशारा करूँगी।"
            if language is Language.HINDI else
            "Jo bhi number dikhe, mujhse poochiye — main uspar ishaara karungi."
        )

    def _locate(self, r: MerchantResponse, utterance: str,
                language: Language) -> None:
        """Point at whatever the merchant named, rather than explaining it.

        The named phrase becomes the anchor itself, so this is not limited to
        the anchors in the seed — "the issue button" works even though nothing
        in the knowledge base has ever heard of it. Resolution happens on the
        client against the real screen; if it cannot be found, the client
        reports that instead of pointing at a guess.
        """
        target = locate.extract_target(utterance)
        if not target:
            r.answer = (
                "Tell me the name of the button or field you are looking for and "
                "I will point at it."
                if language is Language.ENGLISH else
                "जिस बटन या ख़ाने को ढूँढ रहे हैं उसका नाम बताइए, मैं उस पर इशारा करूँगी।"
                if language is Language.HINDI else
                "Jis button ya field ko dhoond rahe hain uska naam bataiye, main "
                "uspar ishaara karungi."
            )
            r.confidence = 0.4
            r.fallback_used = True
            return

        # Try the phrase as spoken first, then without its trailing UI noun —
        # a merchant says "the issue button" where the screen just says "Issue".
        terms = locate.search_terms(target)
        r.highlight_targets = [
            HighlightTarget(
                target_id=f"locate.{index}",
                label=target,
                anchor_text=term,
                severity=Severity.GUIDANCE,
            )
            for index, term in enumerate(terms)
        ]

        r.answer = (
            f"Looking for “{target}” — I am pointing at it now. If my cursor does "
            f"not land on it, it is not on this screen."
            if language is Language.ENGLISH else
            f"“{target}” ढूँढ रही हूँ — उसी पर इशारा कर रही हूँ। अगर कर्सर वहाँ नहीं "
            f"पहुँचा, तो वह इस स्क्रीन पर नहीं है।"
            if language is Language.HINDI else
            f"“{target}” dhoond rahi hoon — usi par ishaara kar rahi hoon. Agar "
            f"cursor wahan nahi pahuncha, to wo is screen par nahi hai."
        )
        r.why_seeing_this = (
            "You asked where something is, so I am showing you rather than "
            "explaining it."
            if language is Language.ENGLISH else
            "आपने पूछा कि यह कहाँ है, इसलिए मैं समझाने के बजाय दिखा रही हूँ।"
            if language is Language.HINDI else
            "Aapne pucha ye kahan hai, isliye main samjhane ke bajay dikha rahi hoon."
        )
        r.what_next = (
            "Ask me what it does once you can see it."
            if language is Language.ENGLISH else
            "दिख जाए तो पूछिए कि यह क्या करता है।"
            if language is Language.HINDI else
            "Dikh jaye to poochiye ki ye kya karta hai."
        )
        r.confidence = 0.75

    def _knowledge_only(self, r: MerchantResponse, utterance: str, topic_hint: str,
                        language: Language) -> None:
        topic = topic_hint or _topic_for_intent(r.intent)
        entries = kb.retrieve(utterance, r.page, r.intent, topic, limit=3)
        r.answer = explain.kb_answer(entries, language)
        r.source_urls = kb.source_urls(entries)
        notice = kb.unverified_notice(entries, language)
        if notice:
            r.uncertainty.append(notice)
        if not entries:
            r.fallback_used = True
            r.confidence = 0.0
            return

        # A definition on its own is a chatbot answer. Anchor it to the
        # merchant's actual screen: quote the real figure and point at the row.
        self._attach_screen_evidence(r, topic, language)

    def _attach_screen_evidence(self, r: MerchantResponse, topic: str,
                                language: Language) -> None:
        """Pair a knowledge answer with real numbers and places on screen."""
        r.highlight_targets = explain.topic_targets(topic)

        wanted = explain.TOPIC_FACT_KEYS.get(topic)
        if not wanted:
            return

        result = self._adapter.settlements(limit=1)
        if not result.ok or not result.rows:
            return

        row = result.rows[0]
        breakdown = explain_settlement(row)
        available = {f.key: f for f in breakdown.facts + settlement_period_facts(row)}
        facts = [available[k] for k in wanted if k in available]
        if not facts:
            return

        r.facts_used = facts
        bits = "; ".join(f"{f.label}: {f.value_text}" for f in facts)
        label = ("On this settlement — " if language is Language.ENGLISH
                 else "इस सेटलमेंट पर — " if language is Language.HINDI
                 else "Is settlement par — ")
        r.answer = f"{r.answer} {label}{bits}."
        r.warnings.extend(breakdown.warnings)

    def _unknown(self, r: MerchantResponse, utterance: str, topic_hint: str,
                 language: Language) -> None:
        # A high bar on purpose: reclassifying a genuinely unknown question as
        # "explain this term" on one weak keyword hit is how an assistant ends
        # up confidently answering something it was never asked.
        entries = kb.retrieve(utterance, r.page, Intent.UNKNOWN, topic_hint,
                              limit=2, min_score=3.0)
        p = explain.phrases(language)
        if entries:
            r.answer = explain.kb_answer(entries, language)
            r.source_urls = kb.source_urls(entries)
            r.intent = Intent.EXPLAIN_TERM
        else:
            r.answer = p.unknown
            r.fallback_used = True
            r.uncertainty.append("I did not understand what you were asking about.")

    # ── Guide-me ─────────────────────────────────────────────────────────────

    def _next_step_response(self, r: MerchantResponse, language: Language
                            ) -> MerchantResponse:
        r.intent = Intent.NEXT_STEP
        if not self.guide.steps:
            r.answer = (
                "There is no guide running. Ask me something like "
                "\"payment link kaise banau\" and I will walk you through it."
                if language is not Language.HINDI else
                "अभी कोई गाइड नहीं चल रही। मुझसे पूछिए, जैसे \"पेमेंट लिंक कैसे बनाऊँ\"।"
            )
            r.confidence = 0.9
            return r

        nxt = self.guide.advance()
        r.steps = list(self.guide.steps)
        r.confidence = 0.9
        if nxt is None:
            r.answer = (
                "That is the whole flow — you have finished every step."
                if language is Language.ENGLISH else
                "बस, पूरी प्रक्रिया हो गई — सारे क़दम पूरे हुए।"
                if language is Language.HINDI else
                "Bas, poori process ho gayi — saare steps complete hue."
            )
            return r

        r.answer = f"{nxt.title}. {nxt.why}"
        r.what_next = nxt.title
        r.why_seeing_this = nxt.why
        if nxt.anchor_text:
            r.highlight_targets = [HighlightTarget(nxt.target_id, nxt.title,
                                                   nxt.anchor_text)]
        r.requires_confirmation = nxt.requires_confirmation
        return r

    # ── Refusals and failures ────────────────────────────────────────────────

    def _refuse_action(self, r: MerchantResponse, kind: str, utterance: str,
                       language: Language) -> MerchantResponse:
        self.deps.audit.record(
            KIND_ACTION_BLOCKED,
            f"refused to perform '{kind}' — read-only by design",
            outcome="blocked",
        )
        r.answer = blocked_action_message(kind, language.value)
        r.requires_confirmation = True
        r.confidence = 0.95
        r.warnings.append("Merchant Mode is read-only. It never moves money.")

        if kind in ("issue_refund",):
            r.steps = explain.refund_steps(language)
            r.highlight_targets = explain.refund_targets()
            r.page = DashboardPage.REFUNDS
            r.intent = Intent.REFUND_TUTORIAL
            self.guide.reset(Intent.REFUND_TUTORIAL, r.steps)
        elif kind in ("create_payment_link", "send_payment_link"):
            r.steps = explain.payment_link_steps(language)
            r.highlight_targets = explain.payment_link_targets()
            r.page = DashboardPage.PAYMENT_LINKS
            r.intent = Intent.CREATE_PAYMENT_LINK_TUTORIAL
            self.guide.reset(Intent.CREATE_PAYMENT_LINK_TUTORIAL, r.steps)

        r.what_next = r.steps[0].title if r.steps else ""
        return r

    def _permission_needed(self, r: MerchantResponse, language: Language
                           ) -> MerchantResponse:
        r.answer = (
            "I need your permission to read the window you are looking at. Nothing is "
            "saved and only the active window is read — turn it on when you are ready."
            if language is Language.ENGLISH else
            "मुझे वह विंडो पढ़ने की अनुमति चाहिए जो आप देख रहे हैं। कुछ भी सेव नहीं होता और "
            "सिर्फ़ यही विंडो पढ़ी जाती है।"
            if language is Language.HINDI else
            "Mujhe wo window padhne ki permission chahiye jo aap dekh rahe hain. Kuch bhi "
            "save nahi hota aur sirf yahi window padhi jaati hai."
        )
        r.requires_confirmation = True
        r.confidence = 1.0
        r.warnings.append("Screen reading is off until you allow it.")
        return r

    def _data_ok(self, r: MerchantResponse, result: DataResult,
                 language: Language) -> bool:
        """Handle adapter failure and emptiness honestly. True means proceed."""
        p = explain.phrases(language)

        if not result.ok:
            r.answer = (
                f"{p.no_data} The dashboard reported: {result.error}"
                if language is Language.ENGLISH else
                f"{p.no_data} डैशबोर्ड ने बताया: {result.error}"
                if language is Language.HINDI else
                f"{p.no_data} Dashboard ne bataya: {result.error}"
            )
            r.confidence = 0.0
            r.fallback_used = True
            r.warnings.append(f"Data source error ({result.error_code}).")
            self.deps.audit.record(KIND_ERROR, f"adapter: {result.error_code}",
                                   outcome="data_unavailable")
            return False

        if not result.rows:
            r.answer = (
                "There is nothing here yet, so there is nothing for me to explain."
                if language is Language.ENGLISH else
                "यहाँ अभी कुछ नहीं है, इसलिए समझाने को कुछ नहीं है।"
                if language is Language.HINDI else
                "Yahan abhi kuch nahi hai, isliye samjhane ko kuch nahi hai."
            )
            r.confidence = 0.9
            return False

        return True

    # ── Model refinement ─────────────────────────────────────────────────────

    async def _maybe_refine(self, r: MerchantResponse, language: Language) -> None:
        draft = r.answer
        refine = self.deps.refine
        if refine is None:
            r.fallback_used = True
            return
        try:
            candidate = await refine(
                explain.REFINE_SYSTEM_PROMPT,
                explain.build_refine_prompt(draft, r.facts_used, language),
            )
        except Exception as exc:
            self.deps.audit.record(KIND_FALLBACK, f"model unavailable: {exc}",
                                   outcome="fallback")
            r.fallback_used = True
            return

        outcome = explain.accept_refinement(candidate, draft, r.facts_used)
        r.answer = outcome.text
        if not outcome.used_model:
            r.fallback_used = True
            if outcome.rejected_reason.startswith("model invented"):
                self.deps.audit.record(KIND_FALLBACK, outcome.rejected_reason,
                                       outcome="blocked")
                r.warnings.append(
                    "The local model tried to change a number, so I used my own "
                    "calculation instead."
                )


def _screen_intro(language: Language, gross: str, net: str,
                  deductions: list) -> str:
    """One sentence pairing what was collected with what was settled."""
    if deductions:
        bits = ", ".join(f"{f.value_text} {f.label.lower()}" for f in deductions)
        if language is Language.HINDI:
            return f"इस स्क्रीन पर कुल {gross} दिख रहा है। {bits} घटने के बाद {net} आपके बैंक जाता है।"
        if language is Language.HINGLISH:
            return f"Is screen par total {gross} dikh raha hai. {bits} katne ke baad {net} aapke bank jaata hai."
        return (f"This screen shows {gross} collected. After {bits}, "
                f"{net} reaches your bank.")
    if language is Language.HINDI:
        return f"इस स्क्रीन पर कुल {gross} दिख रहा है और {net} आपके बैंक पहुँचा।"
    if language is Language.HINGLISH:
        return f"Is screen par total {gross} dikh raha hai aur {net} aapke bank pahuncha."
    return f"This screen shows {gross} collected and {net} reaching your bank."


def _topic_for_intent(intent: Intent) -> str:
    """Fallback topic when the utterance named no recognisable subject."""
    return {
        Intent.EXPLAIN_FEES: "fees",
        Intent.EXPLAIN_REPORT: "reports",
        Intent.EXPLAIN_SETTLEMENT: "settlements",
        Intent.REFUND_TUTORIAL: "refunds",
        Intent.SHOW_FAILED_PAYMENTS: "failed_payments",
        Intent.CREATE_PAYMENT_LINK_TUTORIAL: "payment_links",
    }.get(intent, "")


def _detect_action_demand(utterance: str) -> Optional[str]:
    """Identify a "do it for me" instruction, if there is one.

    Order matters: a sentence can name a refund and a link at once
    ("refund kar do aur link bhej do"), and the refund is the more dangerous
    reading, so it is checked first.
    """
    text = utterance or ""
    if not text.strip():
        return None
    for kind in ("issue_refund", "send_payment_link", "create_payment_link",
                 "message_customer"):
        for rx in _ACTION_DEMANDS[kind]:
            if rx.search(text):
                return kind
    return None


__all__ = [
    "MerchantPipeline",
    "PipelineConfig",
    "PipelineDeps",
    "GuideState",
    "NEVER_AUTOMATED",
]
