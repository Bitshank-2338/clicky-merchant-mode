"""
Intent and language detection for merchant utterances.

Deliberately rule-based rather than model-based:

* it works when Ollama is not installed, which is a hard requirement;
* it is deterministic, so the evaluation harness measures the same thing twice;
* merchant phrasing is a small, closed domain — a classifier would be
  over-engineering.

The patterns cover English, Devanagari Hindi and Roman-script Hinglish, because
"settlement kam kyon aaya" is the actual sentence a shopkeeper says.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from merchant.models import Intent, Language

# ── Language detection ────────────────────────────────────────────────────────

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Roman-script Hindi markers. Only words that are unambiguously Hindi — no
# "me"/"to"/"is", which are ordinary English.
_HINGLISH_MARKERS = {
    "kya", "kyon", "kyu", "kyun", "kaise", "kaisa", "kaha", "kahan", "kab",
    "hota", "hoti", "hote", "hai", "hain", "tha", "thi", "raha", "rahi",
    "mera", "meri", "mere", "mujhe", "aapka", "aapki", "aapke", "apna",
    "batao", "bataiye", "samjhao", "samjhaiye", "dikhao", "dikhaiye",
    "kam", "zyada", "paisa", "paise", "wapas", "nahi", "nahin", "kaun",
    "banau", "banana", "karte", "karna", "karu", "chahiye", "sikhao",
    "matlab", "mein", "aur", "phir", "abhi", "kal", "aaj", "sab", "kuch",
}

_MIN_HINGLISH_HITS = 1


def detect_language(text: str) -> Language:
    """Classify an utterance as English, Hindi or Hinglish."""
    if not text or not text.strip():
        return Language.ENGLISH

    if _DEVANAGARI.search(text):
        # Devanagari present. If it is *mostly* Devanagari call it Hindi;
        # a Devanagari word inside an English sentence is Hinglish.
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return Language.HINDI
        deva = sum(1 for c in letters if "DEVANAGARI" in unicodedata.name(c, ""))
        return Language.HINDI if deva / len(letters) >= 0.5 else Language.HINGLISH

    words = set(re.findall(r"[a-z]+", text.lower()))
    if len(words & _HINGLISH_MARKERS) >= _MIN_HINGLISH_HITS:
        return Language.HINGLISH
    return Language.ENGLISH


# ── Intent detection ──────────────────────────────────────────────────────────
#
# Each rule is (intent, weight, regex). Weights let a specific phrase beat a
# generic one — "settlement kam kyon aaya" must not be swallowed by the generic
# "explain this screen" rule.

_RULES: list[tuple[Intent, float, re.Pattern[str]]] = [
    # Settlement shortfall — the flagship flow.
    (Intent.EXPLAIN_SETTLEMENT, 6.0, re.compile(
        r"settlement.{0,30}(kam|less|low|short|kyon|kyun|why)"
        r"|(kam|less|low|short).{0,30}settlement"
        r"|why.{0,25}(did|is|was).{0,15}(i|my).{0,15}(get|receive|settle)"
        r"|paisa.{0,20}kam"
        r"|कम.{0,20}(आया|मिला)",
        re.I)),
    (Intent.EXPLAIN_SETTLEMENT, 4.0, re.compile(
        r"\bsettlement\b|\bसेटलमेंट\b|\bnet settlement\b|\bsettled amount\b", re.I)),

    # Failed payments.
    (Intent.SHOW_FAILED_PAYMENTS, 6.0, re.compile(
        r"(failed|fail|असफल|फेल).{0,25}(payments?|transactions?|dikhao|show|list|dekh)"
        r"|(dikhao|show me|list|dekhna|dekhu).{0,25}failed"
        r"|kal ke failed",
        re.I)),
    (Intent.EXPLAIN_FAILED_PAYMENT, 5.0, re.compile(
        r"(payment|transaction).{0,25}(failed|fail).{0,25}(kyon|kyun|why|reason|kaaran)"
        r"|why.{0,20}(did|has).{0,20}(this|the|my).{0,20}payment.{0,20}fail"
        r"|failed.{0,15}(kyon|kyun|why)"
        # "Ye payment kyon fail hua?" — question word before the verb.
        r"|(payment|transaction).{0,20}(kyon|kyun|why).{0,15}(fail|failed)"
        r"|(kyon|kyun|why).{0,15}(fail|failed)\s*(hua|hui|ho)",
        re.I)),
    (Intent.SHOW_FAILED_PAYMENTS, 3.0, re.compile(r"\bfailed\b|\bफेल\b", re.I)),

    # Payment links.
    (Intent.CREATE_PAYMENT_LINK_TUTORIAL, 6.0, re.compile(
        r"payment ?link.{0,30}(banana|banau|banaye|kaise|create|make|sikhao|how)"
        r"|(kaise|how|sikhao|teach).{0,30}payment ?link"
        r"|पेमेंट ?लिंक",
        re.I)),
    (Intent.CREATE_PAYMENT_LINK_TUTORIAL, 3.0, re.compile(r"payment ?link", re.I)),

    # Refunds.
    (Intent.REFUND_TUTORIAL, 6.0, re.compile(
        r"refund.{0,30}(kaise|kaisa|how|karte|karna|karu|process|issue|de|dena)"
        r"|(kaise|how).{0,25}refund"
        r"|(customer|grahak).{0,25}(ko|to).{0,25}(refund|paisa wapas)"
        r"|paisa.{0,15}wapas"
        r"|रिफंड",
        re.I)),
    (Intent.EXPLAIN_TERM, 5.5, re.compile(
        r"refund.{0,20}(aur|and|vs|versus).{0,20}reversal"
        r"|reversal.{0,20}(aur|and|vs|versus).{0,20}refund",
        re.I)),
    (Intent.REFUND_TUTORIAL, 3.0, re.compile(r"\brefund\b", re.I)),

    # Fees / tax.
    (Intent.EXPLAIN_FEES, 5.0, re.compile(
        r"\b(fees?|charges?|commission|kitna kata|kata|deduct)\b"
        r"|\bgst\b|\btax on fees\b|\bशुल्क\b",
        re.I)),

    # Reports.
    (Intent.EXPLAIN_REPORT, 5.0, re.compile(
        r"\breport\b.{0,30}(samjh|understand|kaise|padh|read|matlab)"
        r"|(kaise|how).{0,20}\breport\b"
        r"|\breconciliation\b",
        re.I)),

    # Explain this screen.
    (Intent.EXPLAIN_SCREEN, 6.5, re.compile(
        r"(?:(is|this|ye|yeh)\s+)?(screen|page|dashboard|scr(e|ee)n)"
        r".{0,35}(samjhao|samjha|explain|simple|matlab|batao)"
        r"|explain.{0,15}(this|the).{0,15}(screen|page)"
        r"|what.{0,10}(is|am i looking at).{0,15}(this|on).{0,15}(screen|page)?"
        r"|(screen|page).{0,20}(ko|mein).{0,20}samjhao"
        r"|स्क्रीन.{0,20}समझा",
        re.I)),

    # "Where is X?" — outranks every topic rule on purpose. Someone asking to
    # be shown the refund button wants a finger pointed at it, not a tutorial
    # about refunds. `merchant.locate.is_locate_request` is the real gate; the
    # pattern here only has to be broad enough to reach it.
    (Intent.LOCATE_ELEMENT, 6.9, re.compile(
        r"\bwhere\s+(?:is|are|can i find|do i find)\b"
        r"|\b(?:kahan|kidhar)\s+(?:hai|hain|par|pe|milega|milta)\b"
        r"|(?:कहाँ|कहां)\s*(?:है|हैं)"
        # "where it is" / "where they are" — the pronoun form.
        r"|\bwhere\s+(?:it|they|that|this)\s+(?:is|are)\b"
        # A UI noun and a locate verb, in either order: "show me the X button"
        # and "the X button ... can you show me" are the same request.
        r"|\b(?:show|point|find|locate|highlight)\b.{0,40}"
        r"\b(?:button|tab|menu|option|field|icon|column|filter|link|section|row)\b"
        r"|\b(?:button|tab|menu|option|field|icon|column|filter|section|row)\b"
        r".{0,40}\b(?:show|find|locate|highlight|dikha(?:o|iye|na|do)|kahan|kidhar)\b"
        r"|(?:बटन|टैब|मेन्यू|विकल्प).{0,20}(?:दिखा|कहाँ|कहां)",
        re.I)),

    # Next step in an active guide.
    (Intent.NEXT_STEP, 7.0, re.compile(
        r"^\s*(next|aage|agla|ho gaya|done|kar liya|ready|continue|next step)\s*[.!?]?\s*$",
        re.I)),

    # Definitional phrasing. Weight is above every topic rule, but
    # `detect_intent` only lets it win when a merchant topic was also
    # recognised — otherwise we would "explain" things we know nothing about.
    (Intent.EXPLAIN_TERM, 6.6, re.compile(
        r"\bkya (hota|hoti) hai\b|\bक्या (होता|होती) है\b"
        r"|\b(kya|kitna) (farq|antar|difference)\b"
        r"|\bmein kya (farq|antar|difference)\b"
        r"|\bwhat(?:'s| is) (?:the|a|an)\b"
        r"|\bdifference between\b",
        re.I)),

    # Generic "what is this" → term explanation.
    (Intent.EXPLAIN_TERM, 4.0, re.compile(
        r"^\s*(what is|what's|kya (hai|hota hai)|.{0,25}\bkya hota hai\b|"
        r".{0,25}\bmatlab kya\b|.{0,25}\bक्या (है|होता है)\b)",
        re.I)),
    (Intent.EXPLAIN_TERM, 3.5, re.compile(
        r"\bkya (hai|hota|hoti) hai\b|\bmatlab\b|\bmeaning of\b|\bwhat does .{1,30} mean\b",
        re.I)),
]


@dataclass
class IntentDetection:
    intent: Intent
    confidence: float
    language: Language
    matched: list[str] = field(default_factory=list)
    topic_hint: str = ""


# Topic hint keywords, used to steer knowledge-base retrieval and to decide
# which part of the screen to point at.
#
# ORDER IS SIGNIFICANT: first match wins, so the most specific topic must come
# first. "Settlement se tax kya kata jaata hai?" is a question about tax that
# happens to mention settlements; resolving it to "settlements" made Clicky
# point at the UTR and the period instead of the tax line.
_TOPIC_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("tax", re.compile(r"\btax\b|\bgst\b|जीएसटी|कर\b", re.I)),
    ("fees", re.compile(r"\bfees?\b|charge|commission|शुल्क|kata|katta", re.I)),
    ("payment_links", re.compile(r"payment ?link|पेमेंट ?लिंक", re.I)),
    ("refunds", re.compile(r"refund|reversal|रिफंड|wapas", re.I)),
    ("disputes", re.compile(r"dispute|chargeback", re.I)),
    ("failed_payments", re.compile(r"fail|फेल", re.I)),
    ("reports", re.compile(r"report|reconcil", re.I)),
    ("payment_status", re.compile(r"captured|authorized|authoris|pending", re.I)),
    # Broadest last. UTR and payout are settlement vocabulary a merchant may
    # use without ever saying the word "settlement".
    ("settlements", re.compile(r"settlement|सेटलमेंट|\butr\b|payout", re.I)),
]

_MAX_SCORE = 7.0


def detect_intent(text: str) -> IntentDetection:
    """Classify a merchant utterance."""
    language = detect_language(text)
    if not text or not text.strip():
        return IntentDetection(Intent.UNKNOWN, 0.0, language)

    scores: dict[Intent, float] = {}
    matched: dict[Intent, list[str]] = {}

    for intent, weight, rx in _RULES:
        m = rx.search(text)
        if m:
            scores[intent] = max(scores.get(intent, 0.0), weight)
            matched.setdefault(intent, []).append(m.group(0)[:60])

    if not scores:
        return IntentDetection(Intent.UNKNOWN, 0.0, language,
                               topic_hint=_topic_hint(text))

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0

    hint = _topic_hint(text)

    # The locate rule is deliberately broad, so confirm with the stricter
    # checker before letting it beat a topic rule.
    #
    # A locate request that names nothing findable ("where is it?") still stays
    # LOCATE_ELEMENT: the handler answers "tell me what you're looking for",
    # which is far more use to the merchant than a generic "I don't know".
    if best is Intent.LOCATE_ELEMENT:
        from merchant.locate import is_locate_request

        if not is_locate_request(text):
            remaining = [(i, s) for i, s in ranked[1:]
                         if i is not Intent.LOCATE_ELEMENT]
            if not remaining:
                return IntentDetection(Intent.UNKNOWN, 0.0, language, topic_hint=hint)
            best, best_score = remaining[0]
            second = remaining[1][1] if len(remaining) > 1 else 0.0

    # "What is X" is only a term question we can answer if X is a payments term
    # we actually know about. Without a merchant topic, "What is the weather in
    # Mumbai?" would otherwise be classified as something Merchant Mode can
    # explain — and confidently answering out-of-domain questions is exactly
    # the failure mode this product cannot afford.
    if best is Intent.EXPLAIN_TERM and not hint:
        remaining = [(i, s) for i, s in ranked[1:] if i is not Intent.EXPLAIN_TERM]
        if not remaining:
            return IntentDetection(Intent.UNKNOWN, 0.0, language, topic_hint=hint)
        best, best_score = remaining[0]
        second = remaining[1][1] if len(remaining) > 1 else 0.0

    confidence = min(best_score / _MAX_SCORE, 1.0)
    if best_score - second < 1.0 and len(ranked) > 1:
        confidence *= 0.7

    return IntentDetection(
        intent=best,
        confidence=round(confidence, 3),
        language=language,
        matched=matched.get(best, []),
        topic_hint=hint,
    )


def _topic_hint(text: str) -> str:
    for topic, rx in _TOPIC_HINTS:
        if rx.search(text):
            return topic
    return ""


# Intents that must never trigger an action without explicit confirmation.
SENSITIVE_INTENTS = frozenset({
    Intent.REFUND_TUTORIAL,
    Intent.CREATE_PAYMENT_LINK_TUTORIAL,
})
