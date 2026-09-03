"""
Dashboard page detection.

Three signals, strongest first:

1. `dom_map` — the mock dashboard publishes its page id directly. Certain.
2. `url_hint` — a Razorpay dashboard URL path. Near certain.
3. OCR text — scored keyword evidence. Uncertain, and reported as such.

The function returns a confidence alongside the page. A low confidence must
make the caller *ask* rather than assert; `DashboardPage.UNKNOWN` is a valid,
honest answer and the pipeline is built to handle it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from merchant.models import DashboardPage, ScreenContext

# Evidence keywords per page. Weighted: a heading-ish term is worth more than a
# word that could appear anywhere on the dashboard.
_EVIDENCE: dict[DashboardPage, list[tuple[str, float]]] = {
    DashboardPage.SETTLEMENTS: [
        ("settlement", 3.0), ("settlements", 3.0), ("net settlement", 4.0),
        ("utr", 2.5), ("gross amount", 2.5), ("settled on", 2.0),
        ("tax on fees", 2.5), ("razorpay fees", 2.0), ("settlement period", 3.0),
    ],
    DashboardPage.PAYMENTS: [
        ("payments", 2.5), ("payment id", 3.0), ("captured", 1.5),
        ("authorized", 1.5), ("failure reason", 2.5), ("method", 1.0),
        ("date range", 1.5), ("apply filters", 1.5),
    ],
    DashboardPage.REFUNDS: [
        ("refunds", 3.0), ("refund id", 3.5), ("refund type", 3.0),
        ("partial", 1.5), ("processed", 1.0), ("refunded", 1.5),
    ],
    DashboardPage.PAYMENT_LINKS: [
        ("payment links", 3.5), ("payment link", 3.0), ("expire by", 2.5),
        ("short url", 2.0), ("create payment link", 3.5), ("preview link", 2.5),
        ("rzp.io", 2.5),
    ],
    DashboardPage.REPORTS: [
        ("reports", 3.0), ("download report", 3.5), ("generate report", 3.0),
        ("csv", 1.0), ("reconciliation", 2.0),
    ],
    DashboardPage.DISPUTES: [
        ("disputes", 3.5), ("chargeback", 3.5), ("arbitration", 2.5),
        ("evidence", 1.5),
    ],
    DashboardPage.HOME: [
        ("dashboard", 1.5), ("today's collection", 3.0), ("summary", 1.5),
        ("pending settlement", 2.5), ("overview", 1.5),
    ],
}

_URL_PATTERNS: list[tuple[re.Pattern[str], DashboardPage]] = [
    (re.compile(r"/settlements?\b", re.I), DashboardPage.SETTLEMENTS),
    (re.compile(r"/payment[-_]?links?\b", re.I), DashboardPage.PAYMENT_LINKS),
    (re.compile(r"/refunds?\b", re.I), DashboardPage.REFUNDS),
    (re.compile(r"/disputes?\b", re.I), DashboardPage.DISPUTES),
    (re.compile(r"/reports?\b", re.I), DashboardPage.REPORTS),
    (re.compile(r"/transactions?\b", re.I), DashboardPage.PAYMENTS),
    (re.compile(r"/payments?\b", re.I), DashboardPage.PAYMENTS),
    (re.compile(r"[?#]page=home\b|/app/dashboard\b", re.I), DashboardPage.HOME),
]

# Ambiguity guard: if the best score barely beats the runner-up we are not
# actually confident, whatever the absolute score says.
_MIN_MARGIN = 1.5
_STRONG_SCORE = 6.0


@dataclass
class PageDetection:
    page: DashboardPage
    confidence: float
    signal: str          # "dom_map" | "url" | "ocr" | "none"
    runner_up: DashboardPage = DashboardPage.UNKNOWN
    evidence: list[str] = field(default_factory=list)


def detect_page(ctx: ScreenContext) -> PageDetection:
    """Identify the dashboard page currently on screen."""

    # 1. DOM map — the dashboard told us. Trust it.
    dom_page = _page_from_dom(ctx)
    if dom_page is not None:
        return PageDetection(dom_page, 0.99, "dom_map", evidence=["dom_map"])

    # 2. URL.
    if ctx.url_hint:
        for rx, page in _URL_PATTERNS:
            if rx.search(ctx.url_hint):
                return PageDetection(page, 0.92, "url", evidence=[rx.pattern])

    # 3. OCR keyword scoring.
    haystack = f"{ctx.window_title}\n{ctx.ocr_text}".lower()
    if not haystack.strip():
        return PageDetection(DashboardPage.UNKNOWN, 0.0, "none")

    scores: dict[DashboardPage, float] = {}
    hits: dict[DashboardPage, list[str]] = {}
    for page, terms in _EVIDENCE.items():
        total = 0.0
        found: list[str] = []
        for term, weight in terms:
            if term in haystack:
                total += weight
                found.append(term)
        if total:
            scores[page] = total
            hits[page] = found

    if not scores:
        return PageDetection(DashboardPage.UNKNOWN, 0.0, "ocr")

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_page, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    runner_up = ranked[1][0] if len(ranked) > 1 else DashboardPage.UNKNOWN

    margin = best_score - second_score
    # Saturating score → confidence, then penalised when the margin is thin.
    confidence = min(best_score / _STRONG_SCORE, 1.0) * 0.85
    if margin < _MIN_MARGIN:
        confidence *= 0.55

    if confidence < 0.3:
        return PageDetection(DashboardPage.UNKNOWN, confidence, "ocr",
                             runner_up=best_page, evidence=hits.get(best_page, []))

    return PageDetection(best_page, round(confidence, 3), "ocr",
                         runner_up=runner_up, evidence=hits.get(best_page, []))


def _page_from_dom(ctx: ScreenContext) -> DashboardPage | None:
    """Infer the page from published target ids, e.g. 'settlement.gross_amount'."""
    if not ctx.dom_map:
        return None
    prefixes = {k.split(".", 1)[0] for k in ctx.dom_map if "." in k}
    # `nav.*` is present on every page, so it carries no page information.
    prefixes.discard("nav")
    mapping = {
        "settlement": DashboardPage.SETTLEMENTS,
        "payments": DashboardPage.PAYMENTS,
        "refunds": DashboardPage.REFUNDS,
        "link": DashboardPage.PAYMENT_LINKS,
        "reports": DashboardPage.REPORTS,
        "home": DashboardPage.HOME,
    }
    for prefix, page in mapping.items():
        if prefix in prefixes:
            return page
    return None


def page_from_id(value: str) -> DashboardPage:
    """Parse a page id string, tolerating unknown values."""
    try:
        return DashboardPage(str(value).strip().lower())
    except ValueError:
        return DashboardPage.UNKNOWN
