"""
Typed contracts for Clicky Merchant Mode.

Every boundary in the merchant pipeline speaks these types. Nothing in this
module imports PyQt, FastAPI, or any AI SDK — it is pure stdlib so the whole
domain layer stays unit-testable headlessly.

Design rule enforced here: a `MerchantResponse` can only quote a number that is
also present in `facts_used`. See `merchant.explain.verify_no_invented_numbers`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Literal, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────


class DashboardPage(str, Enum):
    """Razorpay dashboard pages Merchant Mode can reason about."""

    HOME = "home"
    PAYMENTS = "payments"
    SETTLEMENTS = "settlements"
    REFUNDS = "refunds"
    PAYMENT_LINKS = "payment_links"
    REPORTS = "reports"
    DISPUTES = "disputes"
    UNKNOWN = "unknown"


class Intent(str, Enum):
    """What the merchant is actually trying to do."""

    EXPLAIN_SETTLEMENT = "explain_settlement"
    EXPLAIN_SCREEN = "explain_screen"
    SHOW_FAILED_PAYMENTS = "show_failed_payments"
    EXPLAIN_FAILED_PAYMENT = "explain_failed_payment"
    CREATE_PAYMENT_LINK_TUTORIAL = "create_payment_link_tutorial"
    REFUND_TUTORIAL = "refund_tutorial"
    EXPLAIN_FEES = "explain_fees"
    EXPLAIN_REPORT = "explain_report"
    EXPLAIN_TERM = "explain_term"
    NEXT_STEP = "next_step"
    UNKNOWN = "unknown"


class Language(str, Enum):
    ENGLISH = "english"
    HINDI = "hindi"
    HINGLISH = "hinglish"


class TargetStrategy(str, Enum):
    """How a highlight target should be resolved to pixels, best first.

    The server never emits pixel coordinates. It emits a semantic target; the
    client (which owns the screenshot) resolves it. `NONE` means the element
    could not be found and Clicky must say so rather than point at a guess.
    """

    DOM_MAP = "dom_map"          # exact rects published by the mock dashboard
    UIA = "uia"                  # Windows UI Automation accessibility tree
    ANCHOR_TEXT = "anchor_text"  # OCR word-box search for the anchor phrase
    VLM = "vlm"                  # vision model, normalised 0-1000
    NONE = "none"


class Severity(str, Enum):
    INFO = "info"
    GUIDANCE = "guidance"
    WARNING = "warning"


class AdapterMode(str, Enum):
    DEMO = "demo"
    RAZORPAY_TEST = "razorpay_test"


# ── Value objects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Money:
    """Integer paise. Never a float — money arithmetic must be exact."""

    paise: int
    currency: str = "INR"

    @classmethod
    def from_rupees(cls, rupees: float | int | str, currency: str = "INR") -> "Money":
        # Round half-up at the paise boundary; Decimal avoids 0.1+0.2 drift.
        from decimal import Decimal, ROUND_HALF_UP

        d = (Decimal(str(rupees)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return cls(int(d), currency)

    @property
    def rupees(self) -> float:
        return self.paise / 100.0

    def format(self) -> str:
        """Indian-grouped currency string, e.g. ₹9,264.00 → '₹9,264'."""
        whole, frac = divmod(abs(self.paise), 100)
        grouped = _indian_group(whole)
        sign = "-" if self.paise < 0 else ""
        symbol = "₹" if self.currency == "INR" else f"{self.currency} "
        if frac:
            return f"{sign}{symbol}{grouped}.{frac:02d}"
        return f"{sign}{symbol}{grouped}"

    def __add__(self, other: "Money") -> "Money":
        _assert_same_currency(self, other)
        return Money(self.paise + other.paise, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        _assert_same_currency(self, other)
        return Money(self.paise - other.paise, self.currency)


def _assert_same_currency(a: Money, b: Money) -> None:
    if a.currency != b.currency:
        raise ValueError(f"currency mismatch: {a.currency} vs {b.currency}")


def _indian_group(n: int) -> str:
    """12345678 -> '1,23,45,678' (Indian digit grouping)."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


@dataclass(frozen=True)
class Fact:
    """One verifiable datum handed to the explanation layer.

    `value_text` is the exact rendered string the explanation is permitted to
    use. Anything the model writes that looks like a number but is not a
    `value_text` here is treated as a hallucination.
    """

    key: str
    label: str
    value_text: str
    source: str  # "demo_adapter" | "razorpay_test_api" | "ocr" | "computed"
    raw_value: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HighlightTarget:
    """A semantic pointer to a UI element. Contains no pixel coordinates."""

    target_id: str
    label: str
    anchor_text: str
    strategy: TargetStrategy = TargetStrategy.ANCHOR_TEXT
    severity: Severity = Severity.GUIDANCE
    # Optional exact rect in *screen* pixels, only ever filled by the dom_map
    # tier on the client side. Never populated by the language model.
    rect: Optional[tuple[int, int, int, int]] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["strategy"] = self.strategy.value
        d["severity"] = self.severity.value
        return d


@dataclass
class Step:
    """One item in the Guide Me checklist."""

    index: int
    title: str
    why: str
    anchor_text: str = ""
    target_id: str = ""
    done: bool = False
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeEntry:
    """One knowledge-base card sourced from official Razorpay documentation."""

    id: str
    topic: str
    title: str
    simple_en: str
    simple_hi: str
    simple_hinglish: str
    source_url: str
    last_reviewed: str
    pages: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def text_for(self, language: Language) -> str:
        if language is Language.HINDI:
            return self.simple_hi
        if language is Language.HINGLISH:
            return self.simple_hinglish
        return self.simple_en


@dataclass
class WordBox:
    """One OCR word with its box in *downscaled screenshot* coordinates."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float = 0.0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class ScreenContext:
    """What Clicky could actually observe. Every field may be absent.

    `raw_text` is ALREADY MASKED by the time a ScreenContext exists — see
    `merchant.masking`. No un-masked screen text is ever stored on this object.
    """

    ocr_text: str = ""
    word_boxes: list[WordBox] = field(default_factory=list)
    window_title: str = ""
    url_hint: str = ""
    dom_map: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    screenshot_width: int = 0
    screenshot_height: int = 0
    captured: bool = False
    masked_field_count: int = 0

    def is_empty(self) -> bool:
        return not self.ocr_text.strip() and not self.dom_map and not self.window_title


@dataclass
class PendingAction:
    """A sensitive action awaiting explicit human confirmation."""

    action_id: str
    kind: str                     # "create_payment_link" | "issue_refund" | ...
    summary: str
    amount_text: str
    masked_customer: str
    created_at: float
    expires_at: float
    consumed: bool = False

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEvent:
    event_id: str
    at: float
    kind: str
    detail: str
    outcome: str = "recorded"
    actor: str = "merchant"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── The response contract ─────────────────────────────────────────────────────


@dataclass
class MerchantResponse:
    """The single structured object every merchant interaction produces."""

    page: DashboardPage = DashboardPage.UNKNOWN
    intent: Intent = Intent.UNKNOWN
    language: Language = Language.ENGLISH
    answer: str = ""
    steps: list[Step] = field(default_factory=list)
    highlight_targets: list[HighlightTarget] = field(default_factory=list)
    facts_used: list[Fact] = field(default_factory=list)
    confidence: float = 0.0
    requires_confirmation: bool = False
    source_urls: list[str] = field(default_factory=list)
    fallback_used: bool = False
    # Extra fields beyond the brief's minimum, needed for an honest UI.
    why_seeing_this: str = ""
    what_next: str = ""
    warnings: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    adapter_mode: AdapterMode = AdapterMode.DEMO
    pending_action_id: Optional[str] = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page.value,
            "intent": self.intent.value,
            "language": self.language.value,
            "answer": self.answer,
            "steps": [s.to_dict() for s in self.steps],
            "highlight_targets": [t.to_dict() for t in self.highlight_targets],
            "facts_used": [f.to_dict() for f in self.facts_used],
            "confidence": round(self.confidence, 3),
            "requires_confirmation": self.requires_confirmation,
            "source_urls": list(self.source_urls),
            "fallback_used": self.fallback_used,
            "why_seeing_this": self.why_seeing_this,
            "what_next": self.what_next,
            "warnings": list(self.warnings),
            "uncertainty": list(self.uncertainty),
            "adapter_mode": self.adapter_mode.value,
            "pending_action_id": self.pending_action_id,
            "request_id": self.request_id,
        }


LOW_CONFIDENCE_THRESHOLD = 0.45
"""Below this, Merchant Mode routes to manual verification instead of asserting."""
