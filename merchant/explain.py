"""
Explanation generation.

Two paths produce the words a merchant hears:

* **Deterministic templates** (this module's default). Built from `Fact`
  objects, available in English, Hindi and Hinglish, and correct by
  construction. They are what runs when Ollama is absent — which is a supported
  configuration, not a degraded one.
* **Local model refinement** (optional). When Ollama is reachable, the template
  answer plus the fact list is handed to it with instructions to improve the
  *phrasing only*. The result is then re-checked by
  `verify_no_invented_numbers`, and any answer that introduces a rupee figure
  not present in the facts is discarded and the template is used instead.

That guard is the reason a language model is safe to use here at all: it can
make the wording warmer, but it cannot change a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from merchant.facts import FailedPaymentSummary, RefundSummary, SettlementBreakdown
from merchant.models import (
    DashboardPage,
    Fact,
    HighlightTarget,
    Intent,
    KnowledgeEntry,
    Language,
    Money,
    Severity,
    Step,
    TargetStrategy,
)

# ── The hallucination guard ───────────────────────────────────────────────────

# A currency figure needs an actual digit after the symbol, and "Rs"/"INR" must
# be a whole word. Without those two constraints this matched "rs," inside
# "...the money is yours, failed..." and suppressed a perfectly correct answer:
# a false positive here is not harmless, it silently deletes a good explanation.
_CURRENCY = re.compile(
    r"₹\s?\d[\d,]*(?:\.\d{1,2})?"
    r"|\b(?:Rs\.?|INR)\s?\d[\d,]*(?:\.\d{1,2})?",
    re.IGNORECASE,
)


def _canon(amount: str) -> str:
    """'₹ 9,264.00' -> '9264'. Trailing '.00' is dropped so formats compare."""
    digits = re.sub(r"[^\d.]", "", amount)
    if "." in digits:
        whole, _, frac = digits.partition(".")
        if frac.rstrip("0") == "":
            return whole
        return f"{whole}.{frac.rstrip('0')}"
    return digits


def verify_no_invented_numbers(answer: str, facts: Sequence[Fact]) -> list[str]:
    """Return every currency figure in `answer` that is not backed by a fact.

    An empty list means the answer only quotes numbers we actually computed.
    This is asserted in tests and enforced at runtime before any generated text
    reaches the merchant.
    """
    if not answer:
        return []

    allowed: set[str] = set()
    for f in facts:
        allowed.add(_canon(f.value_text))
        if f.raw_value is not None:
            allowed.add(_canon(f"{f.raw_value:.2f}"))
            allowed.add(_canon(str(int(f.raw_value)))
                        if float(f.raw_value).is_integer() else _canon(str(f.raw_value)))

    invented: list[str] = []
    for match in _CURRENCY.findall(answer):
        if _canon(match) not in allowed:
            invented.append(match.strip())
    return invented


def strip_to_safe(answer: str, template: str, facts: Sequence[Fact]) -> tuple[str, bool]:
    """Return (safe_answer, used_fallback). Discards an answer that invents money."""
    if verify_no_invented_numbers(answer, facts):
        return template, True
    return answer, False


# ── Localised phrasing ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Phrases:
    settlement_intro: str
    settlement_calc: str
    settlement_close: str
    deduction_line: str
    failed_intro: str
    failed_none: str
    failed_caution: str
    refund_intro: str
    link_intro: str
    screen_intro: str
    no_data: str
    cannot_see: str
    unknown: str
    why_label: str
    next_label: str
    incomplete: str
    demo_note: str


_EN = Phrases(
    settlement_intro="Your customers paid {gross} in this settlement period.",
    settlement_calc="After {deductions}, the amount that reaches your bank is {net}.",
    settlement_close="So {shortfall} in total was taken out before the money reached you.",
    deduction_line="{label} of {value}",
    failed_intro="You have {count} failed payment(s) worth {total}.",
    failed_none="Good news — there are no failed payments here.",
    failed_caution=("A failed payment means the money never reached you. If the customer "
                    "was debited, banks usually return it on their own. Asking them to try "
                    "again may work, but nobody can promise it will."),
    refund_intro="A refund sends money back to your customer from what you have already received.",
    link_intro="A payment link is a small web page you send a customer so they can pay you.",
    screen_intro="Here is what you are looking at.",
    no_data="I cannot see any data on this screen, so I will not guess.",
    cannot_see="I could not read that from your screen.",
    unknown="I do not know this one well enough to answer safely. Please check the Razorpay help page or ask their support.",
    why_label="Why you are seeing this",
    next_label="What to do next",
    incomplete="Some numbers are not shown on this screen, so this breakdown is incomplete.",
    demo_note="Showing demo data, not your real account.",
)

_HI = Phrases(
    settlement_intro="इस सेटलमेंट अवधि में आपके ग्राहकों ने {gross} दिए।",
    settlement_calc="{deductions} कटने के बाद, आपके बैंक में {net} पहुँचता है।",
    settlement_close="यानी पैसा आने से पहले कुल {shortfall} काटा गया।",
    deduction_line="{label} {value}",
    failed_intro="आपके यहाँ {count} पेमेंट फेल हुए हैं, कुल {total} के।",
    failed_none="अच्छी बात है — यहाँ कोई फेल पेमेंट नहीं है।",
    failed_caution=("फेल पेमेंट का मतलब है पैसा आप तक पहुँचा ही नहीं। अगर ग्राहक के खाते से "
                    "कट गया था, तो बैंक आमतौर पर खुद वापस कर देता है। दोबारा कोशिश करने को "
                    "कह सकते हैं, पर यह पक्का नहीं कहा जा सकता कि सफल होगा।"),
    refund_intro="रिफंड का मतलब है जो पैसा आपको मिल चुका है, उसे ग्राहक को वापस भेजना।",
    link_intro="पेमेंट लिंक एक छोटा वेब पेज है जो आप ग्राहक को भेजते हैं ताकि वे आपको पैसे दे सकें।",
    screen_intro="आप जो देख रहे हैं, वह यह है।",
    no_data="इस स्क्रीन पर मुझे कोई जानकारी नहीं दिख रही, इसलिए मैं अंदाज़ा नहीं लगाऊँगी।",
    cannot_see="यह मुझे आपकी स्क्रीन पर नहीं मिला।",
    unknown="यह मुझे ठीक से नहीं पता, इसलिए मैं अंदाज़ा नहीं लगाऊँगी। कृपया Razorpay की मदद वाली जगह देखें।",
    why_label="आपको यह क्यों दिख रहा है",
    next_label="अब आगे क्या करें",
    incomplete="इस स्क्रीन पर कुछ आँकड़े नहीं दिख रहे, इसलिए यह ब्यौरा अधूरा है।",
    demo_note="यह डेमो डेटा है, आपका असली खाता नहीं।",
)

_HINGLISH = Phrases(
    settlement_intro="Is settlement period mein aapke customers ne {gross} diye the.",
    settlement_calc="{deductions} katne ke baad, aapke bank mein {net} aata hai.",
    settlement_close="Matlab paisa aane se pehle total {shortfall} kata hai.",
    deduction_line="{label} {value}",
    failed_intro="Aapke {count} payment fail hue hain, total {total} ke.",
    failed_none="Achhi baat hai — yahan koi failed payment nahi hai.",
    failed_caution=("Failed payment ka matlab hai paisa aap tak pahuncha hi nahi. Agar "
                    "customer ke account se kat gaya tha, to bank aam taur par khud wapas "
                    "kar deta hai. Dobara try karne ko keh sakte hain, par pakka nahi kaha "
                    "ja sakta ki successful hoga."),
    refund_intro="Refund matlab jo paisa aapko mil chuka hai, wo customer ko wapas bhejna.",
    link_intro="Payment link ek chhota web page hai jo aap customer ko bhejte hain taaki wo aapko paisa de sakein.",
    screen_intro="Aap jo dekh rahe hain, wo ye hai.",
    no_data="Is screen par mujhe koi data nahi dikh raha, isliye main andaaza nahi lagaungi.",
    cannot_see="Ye mujhe aapki screen par nahi mila.",
    unknown="Ye mujhe theek se nahi pata, isliye main guess nahi karungi. Razorpay ki help page dekh lijiye.",
    why_label="Aapko ye kyon dikh raha hai",
    next_label="Ab aage kya karein",
    incomplete="Is screen par kuch numbers nahi dikh rahe, isliye ye breakdown adhoora hai.",
    demo_note="Ye demo data hai, aapka asli account nahi.",
)

_PHRASES = {
    Language.ENGLISH: _EN,
    Language.HINDI: _HI,
    Language.HINGLISH: _HINGLISH,
}


def phrases(language: Language) -> Phrases:
    return _PHRASES.get(language, _EN)


def _join(items: Sequence[str], language: Language) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    joiner = " और " if language is Language.HINDI else " aur " if language is Language.HINGLISH else " and "
    return ", ".join(items[:-1]) + joiner + items[-1]


# ── Settlement explanation ────────────────────────────────────────────────────

_DEDUCTION_LABELS = {
    Language.ENGLISH: {"fees": "fees", "tax": "tax on those fees",
                       "refunds": "refunds", "disputes": "disputes"},
    Language.HINDI: {"fees": "फीस", "tax": "फीस पर टैक्स",
                     "refunds": "रिफंड", "disputes": "विवाद"},
    Language.HINGLISH: {"fees": "fees", "tax": "fees par tax",
                        "refunds": "refunds", "disputes": "disputes"},
}


def settlement_answer(bd: SettlementBreakdown, language: Language) -> str:
    """Deterministic settlement explanation built only from checked facts."""
    p = phrases(language)
    by_key = {f.key: f for f in bd.facts}

    if not bd.complete:
        gross = by_key.get("gross_amount")
        net = by_key.get("net_amount")
        parts = [p.incomplete]
        if gross and net:
            parts.append(
                p.settlement_intro.format(gross=gross.value_text)
                + " "
                + (f"The dashboard shows {net.value_text} reaching your bank."
                   if language is Language.ENGLISH else
                   f"डैशबोर्ड दिखा रहा है कि {net.value_text} आपके बैंक पहुँचा।"
                   if language is Language.HINDI else
                   f"Dashboard dikha raha hai ki {net.value_text} aapke bank pahuncha.")
            )
        parts.extend(bd.warnings)
        return " ".join(x for x in parts if x)

    gross = by_key["gross_amount"]
    net = by_key["net_amount"]
    labels = _DEDUCTION_LABELS[language]

    deduction_bits: list[str] = []
    for key in ("fees", "tax", "refunds", "disputes"):
        fact = by_key.get(key)
        if fact is None or (fact.raw_value is not None and abs(fact.raw_value) < 0.005):
            continue
        deduction_bits.append(
            p.deduction_line.format(label=labels[key], value=fact.value_text)
            if language is Language.ENGLISH
            else f"{fact.value_text} {labels[key]}"
        )

    adj = by_key.get("adjustments")
    if adj is not None and adj.raw_value not in (None, 0) and abs(adj.raw_value) >= 0.005:
        word = ("adjustments" if language is Language.ENGLISH
                else "एडजस्टमेंट" if language is Language.HINDI else "adjustments")
        deduction_bits.append(f"{adj.value_text} {word}")

    out = [p.settlement_intro.format(gross=gross.value_text)]
    if deduction_bits:
        out.append(p.settlement_calc.format(
            deductions=_join(deduction_bits, language), net=net.value_text))
    else:
        out.append(
            f"Nothing was deducted, so the full {net.value_text} reached your bank."
            if language is Language.ENGLISH else
            f"कुछ नहीं कटा, इसलिए पूरे {net.value_text} आपके बैंक पहुँचे।"
            if language is Language.HINDI else
            f"Kuch nahi kata, isliye poore {net.value_text} aapke bank pahunche.")

    shortfall = by_key.get("shortfall")
    if shortfall is not None and shortfall.raw_value:
        out.append(p.settlement_close.format(shortfall=shortfall.value_text))

    out.extend(bd.warnings)
    return " ".join(x for x in out if x)


SETTLEMENT_TARGETS = [
    ("settlement.gross_amount", "Gross amount", "Gross amount"),
    ("settlement.fees", "Razorpay fees", "Razorpay fees"),
    ("settlement.tax", "Tax on fees", "Tax on fees"),
    ("settlement.refunds", "Refunds", "Refunds"),
    ("settlement.adjustments", "Adjustments", "Adjustments"),
    ("settlement.net_amount", "Net settlement", "Net settlement"),
]


def settlement_targets_all() -> list[HighlightTarget]:
    """Every settlement row, for when we have no breakdown to filter by."""
    return [
        HighlightTarget(target_id=tid, label=label, anchor_text=anchor,
                        strategy=TargetStrategy.ANCHOR_TEXT,
                        severity=Severity.INFO if tid == "settlement.net_amount"
                        else Severity.GUIDANCE)
        for tid, label, anchor in SETTLEMENT_TARGETS
    ]


def settlement_targets(bd: SettlementBreakdown) -> list[HighlightTarget]:
    """Point only at the lines that actually carry a number we quoted."""
    by_key = {f.key: f for f in bd.facts}
    key_for = {
        "settlement.gross_amount": "gross_amount",
        "settlement.fees": "fees",
        "settlement.tax": "tax",
        "settlement.refunds": "refunds",
        "settlement.adjustments": "adjustments",
        "settlement.net_amount": "net_amount",
    }
    # Rows that are zero were not mentioned in the answer, so pointing at them
    # would be noise. Gross and net are always shown, zero or not.
    always = {"gross_amount", "net_amount"}
    out: list[HighlightTarget] = []
    for target_id, label, anchor in SETTLEMENT_TARGETS:
        key = key_for[target_id]
        fact = by_key.get(key)
        if fact is None:
            continue
        if key not in always and fact.raw_value is not None and abs(fact.raw_value) < 0.005:
            continue
        out.append(HighlightTarget(
            target_id=target_id, label=label, anchor_text=anchor,
            strategy=TargetStrategy.ANCHOR_TEXT,
            severity=Severity.INFO if target_id == "settlement.net_amount"
            else Severity.GUIDANCE,
        ))
    return out


# ── Failed payments ───────────────────────────────────────────────────────────


def failed_payments_answer(summary: FailedPaymentSummary, language: Language) -> str:
    p = phrases(language)
    if summary.count == 0:
        return p.failed_none

    total = summary.total.format() if summary.total else ""
    intro = p.failed_intro.format(count=summary.count, total=total) if total else (
        f"You have {summary.count} failed payment(s)." if language is Language.ENGLISH
        else f"आपके यहाँ {summary.count} पेमेंट फेल हुए हैं।" if language is Language.HINDI
        else f"Aapke {summary.count} payment fail hue hain.")

    reason_bits = []
    from merchant.facts import _humanise_reason  # local import: same package
    for reason, n in sorted(summary.reasons.items(), key=lambda kv: -kv[1]):
        reason_bits.append(f"{n} × {_humanise_reason(reason, language.value)}")
    reasons = ("Reasons shown: " if language is Language.ENGLISH
               else "कारण: " if language is Language.HINDI
               else "Reasons: ") + ", ".join(reason_bits) + "." if reason_bits else ""

    return " ".join(x for x in (intro, reasons, p.failed_caution) if x)


def failed_payment_steps(language: Language) -> list[Step]:
    if language is Language.HINDI:
        titles = [
            ("बाएँ मेन्यू में Payments पर जाएँ", "फेल पेमेंट यहीं दिखते हैं।"),
            ("तारीख़ की सीमा चुनें", "कल की तारीख़ चुनें ताकि सिर्फ़ कल के पेमेंट दिखें।"),
            ("Status में Failed चुनें", "इससे सिर्फ़ फेल पेमेंट बचेंगे।"),
            ("Apply filters दबाएँ", "फ़िल्टर लागू होने पर ही सूची बदलेगी।"),
            ("Failure reason कॉलम पढ़ें", "यहाँ लिखा होता है कि पेमेंट क्यों रुका।"),
        ]
    elif language is Language.HINGLISH:
        titles = [
            ("Left menu mein Payments par jaayein", "Failed payments yahin dikhte hain."),
            ("Date range choose karein", "Kal ki date select karein taaki sirf kal ke payment dikhein."),
            ("Status mein Failed select karein", "Isse sirf failed payments bachenge."),
            ("Apply filters dabayein", "Filter lagne ke baad hi list badlegi."),
            ("Failure reason column padhein", "Yahan likha hota hai ki payment kyon ruka."),
        ]
    else:
        titles = [
            ("Open Payments from the left menu", "Failed payments live on this page."),
            ("Set the date range", "Pick yesterday so only yesterday's payments show."),
            ("Choose Failed in the Status filter", "This leaves only the failed ones."),
            ("Press Apply filters", "The list only changes once filters are applied."),
            ("Read the Failure reason column", "It says why each payment stopped."),
        ]
    anchors = [
        ("nav.payments", "Payments"),
        ("payments.date_filter", "Date range"),
        ("payments.status_filter", "Status"),
        ("payments.apply_filter", "Apply filters"),
        ("payments.error_reason", "Failure reason"),
    ]
    return [
        Step(index=i, title=t, why=w, target_id=anchors[i][0], anchor_text=anchors[i][1])
        for i, (t, w) in enumerate(titles)
    ]


def failed_payment_targets() -> list[HighlightTarget]:
    return [
        HighlightTarget("nav.payments", "Payments menu", "Payments"),
        HighlightTarget("payments.date_filter", "Date range filter", "Date range"),
        HighlightTarget("payments.status_filter", "Status filter", "Status"),
        HighlightTarget("payments.failed_option", "Failed option", "Failed"),
        HighlightTarget("payments.apply_filter", "Apply filters button", "Apply filters"),
        HighlightTarget("payments.error_reason", "Failure reason column", "Failure reason"),
    ]


# ── Payment link tutorial ─────────────────────────────────────────────────────


def payment_link_steps(language: Language) -> list[Step]:
    if language is Language.HINDI:
        rows = [
            ("रकम भरें", "ग्राहक को कितना देना है, वही यहाँ लिखें।", "link.amount", "Amount"),
            ("विवरण लिखें", "ग्राहक को दिखेगा कि पैसा किस चीज़ का है।", "link.description", "Description"),
            ("समय सीमा तय करें", "लिंक कब तक चलेगा — पुराने लिंक बंद रहें तो सुरक्षित है।", "link.expiry", "Expire by"),
            ("ग्राहक का नाम भरें", "बाद में पहचानने में आसानी होती है।", "link.customer_name", "Customer name"),
            ("फ़ोन नंबर भरें", "इसी पर लिंक जाएगा, इसलिए ध्यान से जाँचें।", "link.customer_contact", "Phone number"),
            ("Preview link देखें", "भेजने से पहले ग्राहक को क्या दिखेगा, वह देख लें।", "link.preview", "Preview link"),
            ("आप ख़ुद Create payment link दबाएँ", "यह आख़िरी क़दम आपका है — मैं यह नहीं दबाऊँगी।",
             "link.create_button", "Create payment link"),
        ]
    elif language is Language.HINGLISH:
        rows = [
            ("Amount bharein", "Customer ko kitna dena hai, wahi yahan likhein.", "link.amount", "Amount"),
            ("Description likhein", "Customer ko dikhega ki paisa kis cheez ka hai.", "link.description", "Description"),
            ("Expiry set karein", "Link kab tak chalega — purane link band rahein to safe hai.", "link.expiry", "Expire by"),
            ("Customer ka naam bharein", "Baad mein pehchanne mein aasani hoti hai.", "link.customer_name", "Customer name"),
            ("Phone number bharein", "Isi par link jayega, isliye dhyan se check karein.", "link.customer_contact", "Phone number"),
            ("Preview link dekhein", "Bhejne se pehle customer ko kya dikhega wo dekh lein.", "link.preview", "Preview link"),
            ("Aap khud Create payment link dabayein", "Ye aakhri step aapka hai — main ye nahi dabaungi.",
             "link.create_button", "Create payment link"),
        ]
    else:
        rows = [
            ("Enter the amount", "This is exactly what the customer will be asked to pay.", "link.amount", "Amount"),
            ("Write a description", "The customer sees this, so it should say what the money is for.", "link.description", "Description"),
            ("Set an expiry", "Old links going stale is safer than leaving them open forever.", "link.expiry", "Expire by"),
            ("Add the customer's name", "It makes the link easy to recognise later.", "link.customer_name", "Customer name"),
            ("Add the phone number", "The link goes here, so check it carefully.", "link.customer_contact", "Phone number"),
            ("Use Preview link", "See what the customer will see before anything is sent.", "link.preview", "Preview link"),
            ("Press Create payment link yourself", "This last step is yours — I will not press it.",
             "link.create_button", "Create payment link"),
        ]
    return [
        Step(index=i, title=t, why=w, target_id=tid, anchor_text=anchor,
             requires_confirmation=(tid == "link.create_button"))
        for i, (t, w, tid, anchor) in enumerate(rows)
    ]


def payment_link_targets() -> list[HighlightTarget]:
    return [
        HighlightTarget("link.amount", "Amount field", "Amount"),
        HighlightTarget("link.description", "Description field", "Description"),
        HighlightTarget("link.expiry", "Expiry field", "Expire by"),
        HighlightTarget("link.customer_name", "Customer name field", "Customer name"),
        HighlightTarget("link.customer_contact", "Phone number field", "Phone number"),
        HighlightTarget("link.preview", "Preview button", "Preview link"),
        HighlightTarget("link.create_button", "Create button", "Create payment link",
                        severity=Severity.WARNING),
    ]


# ── Refund tutorial ───────────────────────────────────────────────────────────


def refund_steps(language: Language) -> list[Step]:
    if language is Language.HINDI:
        rows = [
            ("पहले तय करें कि रिफंड सही है या नहीं", "सामान वापस आया? सेवा नहीं दी गई? कारण साफ़ होना चाहिए।", "nav.payments", "Payments"),
            ("Payments में वह पेमेंट ढूँढें", "रिफंड हमेशा किसी असली पेमेंट पर ही होता है।", "payments.table", "Payment ID"),
            ("रकम और ग्राहक जाँचें", "ग़लत ग्राहक को रिफंड वापस नहीं लिया जा सकता।", "payments.table", "Payment ID"),
            ("पूरा या आंशिक रिफंड चुनें", "आंशिक रिफंड तब, जब सिर्फ़ कुछ सामान वापस आया हो।", "refunds.type", "Refund type"),
            ("आप ख़ुद रिफंड की पुष्टि करें", "यह वापस नहीं लिया जा सकता — इसलिए यह क़दम आपका है।", "refunds.table", "Refund ID"),
        ]
    elif language is Language.HINGLISH:
        rows = [
            ("Pehle decide karein ki refund sahi hai ya nahi", "Saaman wapas aaya? Service nahi di? Reason clear hona chahiye.", "nav.payments", "Payments"),
            ("Payments mein wo payment dhoondein", "Refund hamesha kisi asli payment par hi hota hai.", "payments.table", "Payment ID"),
            ("Amount aur customer check karein", "Galat customer ko refund wapas nahi liya ja sakta.", "payments.table", "Payment ID"),
            ("Full ya partial refund chunein", "Partial tab, jab sirf kuch saaman wapas aaya ho.", "refunds.type", "Refund type"),
            ("Aap khud refund confirm karein", "Ye wapas nahi liya ja sakta — isliye ye step aapka hai.", "refunds.table", "Refund ID"),
        ]
    else:
        rows = [
            ("Decide whether a refund is right", "Goods returned? Service not delivered? The reason should be clear.", "nav.payments", "Payments"),
            ("Find the payment in Payments", "A refund always sits on top of a real payment.", "payments.table", "Payment ID"),
            ("Check the amount and the customer", "A refund sent to the wrong customer cannot be pulled back.", "payments.table", "Payment ID"),
            ("Choose full or partial", "Partial is for when only some items came back.", "refunds.type", "Refund type"),
            ("Confirm the refund yourself", "This cannot be undone, so this step is yours.", "refunds.table", "Refund ID"),
        ]
    return [
        Step(index=i, title=t, why=w, target_id=tid, anchor_text=anchor,
             requires_confirmation=(i == len(rows) - 1))
        for i, (t, w, tid, anchor) in enumerate(rows)
    ]


def refund_targets() -> list[HighlightTarget]:
    return [
        HighlightTarget("nav.payments", "Payments menu", "Payments"),
        HighlightTarget("payments.table", "Payment list", "Payment ID"),
        HighlightTarget("refunds.table", "Refund list", "Refund ID"),
        HighlightTarget("refunds.type", "Refund type", "Refund type",
                        severity=Severity.WARNING),
    ]


# ── Topic → on-screen evidence ────────────────────────────────────────────────
#
# A knowledge-base answer alone is just a chatbot reply. What makes this
# Merchant Mode is pairing the explanation with the place on the merchant's
# own screen that the explanation is about.

TOPIC_TARGETS: dict[str, list[HighlightTarget]] = {
    "fees": [
        HighlightTarget("settlement.fees", "Razorpay fees", "Razorpay fees"),
        HighlightTarget("settlement.tax", "Tax on fees", "Tax on fees"),
    ],
    "tax": [
        HighlightTarget("settlement.tax", "Tax on fees", "Tax on fees"),
        HighlightTarget("settlement.fees", "Razorpay fees", "Razorpay fees"),
    ],
    "settlements": [
        HighlightTarget("settlement.net_amount", "Net settlement", "Net settlement"),
        HighlightTarget("settlement.period", "Settlement period", "Settlement period"),
        HighlightTarget("settlement.utr", "UTR", "UTR"),
    ],
    "settlement_timelines": [
        HighlightTarget("settlement.period", "Settlement period", "Settlement period"),
        HighlightTarget("settlement.status", "Status", "Status"),
    ],
    "refunds": [
        HighlightTarget("refunds.table", "Refund list", "Refund ID"),
        HighlightTarget("refunds.type", "Refund type", "Refund type"),
    ],
    "failed_payments": [
        HighlightTarget("payments.error_reason", "Failure reason", "Failure reason"),
        HighlightTarget("payments.status_filter", "Status filter", "Status"),
    ],
    "payment_status": [
        HighlightTarget("payments.status_filter", "Status filter", "Status"),
        HighlightTarget("payments.table", "Payment list", "Payment ID"),
    ],
    "payment_links": [
        HighlightTarget("link.amount", "Amount field", "Amount"),
        HighlightTarget("link.expiry", "Expiry field", "Expire by"),
    ],
    "reports": [
        HighlightTarget("reports.download", "Download report", "Download report"),
    ],
}

# Which settlement fact keys are worth quoting for a given topic.
TOPIC_FACT_KEYS: dict[str, tuple[str, ...]] = {
    "fees": ("fees", "tax"),
    "tax": ("tax", "fees"),
    "settlements": ("gross_amount", "net_amount", "period", "utr", "status"),
    "settlement_timelines": ("period", "settled_on", "status"),
}


def topic_targets(topic: str) -> list[HighlightTarget]:
    return list(TOPIC_TARGETS.get(topic, []))


def reports_targets() -> list[HighlightTarget]:
    return list(TOPIC_TARGETS["reports"])


# ── Screen explanation ────────────────────────────────────────────────────────


_SCREEN_BLURB: dict[DashboardPage, dict[Language, str]] = {
    DashboardPage.SETTLEMENTS: {
        Language.ENGLISH: ("This is the Settlements page. Each row is one batch of money "
                           "moving from Razorpay to your bank. Gross amount is what customers "
                           "paid, then fees, tax on those fees and any refunds are taken off, "
                           "and Net settlement is what actually reaches your account."),
        Language.HINDI: ("यह Settlements पेज है। हर पंक्ति एक बार पैसा Razorpay से आपके बैंक "
                         "जाने का हिसाब है। Gross amount वह है जो ग्राहकों ने दिया, फिर फीस, "
                         "फीस पर टैक्स और रिफंड घटते हैं, और Net settlement वह है जो असल में "
                         "आपके खाते में पहुँचता है।"),
        Language.HINGLISH: ("Ye Settlements page hai. Har row ek baar paisa Razorpay se aapke "
                            "bank jaane ka hisaab hai. Gross amount wo hai jo customers ne diya, "
                            "phir fees, fees par tax aur refunds katte hain, aur Net settlement "
                            "wo hai jo asal mein aapke account mein pahunchta hai."),
    },
    DashboardPage.PAYMENTS: {
        Language.ENGLISH: ("This is the Payments page. Every attempt to pay you appears here, "
                           "successful or not. Status tells you what happened: captured means "
                           "the money is yours, failed means it never arrived."),
        Language.HINDI: ("यह Payments पेज है। आपको पैसे देने की हर कोशिश यहाँ दिखती है, सफल हो "
                         "या न हो। Status बताता है क्या हुआ: captured मतलब पैसा आपका है, failed "
                         "मतलब पैसा आया ही नहीं।"),
        Language.HINGLISH: ("Ye Payments page hai. Aapko paisa dene ki har koshish yahan dikhti "
                            "hai, successful ho ya na ho. Status batata hai kya hua: captured "
                            "matlab paisa aapka hai, failed matlab paisa aaya hi nahi."),
    },
    DashboardPage.REFUNDS: {
        Language.ENGLISH: ("This is the Refunds page. Each row is money you sent back to a "
                           "customer. Refund type says whether the whole payment went back "
                           "or only part of it."),
        Language.HINDI: ("यह Refunds पेज है। हर पंक्ति वह पैसा है जो आपने ग्राहक को वापस भेजा। "
                         "Refund type बताता है कि पूरा पेमेंट वापस गया या सिर्फ़ कुछ हिस्सा।"),
        Language.HINGLISH: ("Ye Refunds page hai. Har row wo paisa hai jo aapne customer ko "
                            "wapas bheja. Refund type batata hai ki poora payment wapas gaya "
                            "ya sirf kuch hissa."),
    },
    DashboardPage.PAYMENT_LINKS: {
        Language.ENGLISH: ("This is the Payment Links page. A payment link is a small page you "
                           "send someone so they can pay you without visiting your shop."),
        Language.HINDI: ("यह Payment Links पेज है। पेमेंट लिंक एक छोटा पेज है जो आप किसी को भेजते "
                         "हैं ताकि वे दुकान आए बिना आपको पैसे दे सकें।"),
        Language.HINGLISH: ("Ye Payment Links page hai. Payment link ek chhota page hai jo aap "
                            "kisi ko bhejte hain taaki wo dukaan aaye bina aapko paisa de sakein."),
    },
    DashboardPage.REPORTS: {
        Language.ENGLISH: ("This is the Reports page. You can download a file of your payments "
                           "or settlements, which is what your accountant usually wants."),
        Language.HINDI: ("यह Reports पेज है। यहाँ से आप अपने पेमेंट या सेटलमेंट की फ़ाइल डाउनलोड "
                         "कर सकते हैं, जो आमतौर पर आपके अकाउंटेंट को चाहिए होती है।"),
        Language.HINGLISH: ("Ye Reports page hai. Yahan se aap apne payments ya settlements ki "
                            "file download kar sakte hain, jo aam taur par aapke accountant ko "
                            "chahiye hoti hai."),
    },
    DashboardPage.HOME: {
        Language.ENGLISH: "This is the dashboard home, a summary of today's money.",
        Language.HINDI: "यह डैशबोर्ड का होम है — आज के पैसे का सारांश।",
        Language.HINGLISH: "Ye dashboard ka home hai — aaj ke paise ka summary.",
    },
}


def screen_answer(page: DashboardPage, language: Language,
                  facts: Sequence[Fact] = ()) -> str:
    blurbs = _SCREEN_BLURB.get(page)
    if not blurbs:
        p = phrases(language)
        return (f"{p.screen_intro} {p.unknown}")
    text = blurbs.get(language, blurbs[Language.ENGLISH])
    if facts:
        bits = "; ".join(f"{f.label}: {f.value_text}" for f in facts[:6])
        label = ("On this screen right now — " if language is Language.ENGLISH
                 else "अभी इस स्क्रीन पर — " if language is Language.HINDI
                 else "Abhi is screen par — ")
        text = f"{text} {label}{bits}."
    return text


# ── Knowledge-base backed answers ─────────────────────────────────────────────


def kb_answer(entries: Sequence[KnowledgeEntry], language: Language,
              fallback_unknown: bool = True) -> str:
    if not entries:
        return phrases(language).unknown if fallback_unknown else ""
    return " ".join(e.text_for(language) for e in entries[:2]).strip()


# ── Optional local-model refinement ───────────────────────────────────────────


REFINE_SYSTEM_PROMPT = """You rewrite explanations for Indian shopkeepers who are new to
online payments. You are given a DRAFT and a list of FACTS.

Absolute rules:
- Never change, add or remove any number, amount or currency figure. Every ₹ figure in your
  output must appear character-for-character in the FACTS list.
- Never add information that is not in the DRAFT. Do not guess policies, timelines or fees.
- Keep the same language as the DRAFT (English, Hindi or Hinglish). Do not translate.
- Keep it under 90 words. Warm, plain, no jargon, no markdown, no bullet points.

Return only the rewritten explanation."""


def build_refine_prompt(draft: str, facts: Sequence[Fact], language: Language) -> str:
    fact_lines = "\n".join(f"- {f.label}: {f.value_text}" for f in facts) or "- (none)"
    return (
        f"LANGUAGE: {language.value}\n\n"
        f"FACTS (the only numbers you may use):\n{fact_lines}\n\n"
        f"DRAFT:\n{draft}\n\n"
        "Rewrite the DRAFT."
    )


@dataclass
class RefineResult:
    text: str
    used_model: bool
    rejected_reason: str = ""


def accept_refinement(candidate: str, draft: str, facts: Sequence[Fact]) -> RefineResult:
    """Apply the guard to a model-refined answer. Falls back to the draft."""
    cleaned = (candidate or "").strip()
    if not cleaned:
        return RefineResult(draft, False, "model returned nothing")
    if len(cleaned) > 1200:
        return RefineResult(draft, False, "model response too long")
    invented = verify_no_invented_numbers(cleaned, facts)
    if invented:
        return RefineResult(draft, False,
                            f"model invented amounts: {', '.join(invented[:3])}")
    return RefineResult(cleaned, True)
