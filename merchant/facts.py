"""
Structured fact extraction.

Every rupee figure Merchant Mode is allowed to say out loud is produced here,
by arithmetic over adapter data. The language model never computes money and
never sees a raw settlement row — it receives a list of `Fact` objects and may
only rephrase them.

Two invariants this module exists to protect:

1. **No silent zeros.** A missing field is `None`, not `0`. If a settlement is
   missing its fee breakdown we report the gap; we do not compute a total that
   quietly assumes fees were nil.
2. **Arithmetic is checked against the source.** We recompute the net
   settlement from its components and compare with the net the dashboard
   reports. A mismatch becomes a visible caveat, never a silent correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from merchant.models import Fact, Money

# The settlement identity, as documented by Razorpay:
#   net = gross - fees - tax - refunds + adjustments - disputes
_COMPONENTS = ("gross_amount", "fees", "tax", "refunds", "adjustments", "disputes")

_SIGNS = {
    "gross_amount": +1,
    "fees": -1,
    "tax": -1,
    "refunds": -1,
    "adjustments": +1,   # already signed in the source data
    "disputes": -1,
}

_LABELS = {
    "gross_amount": "Gross amount",
    "fees": "Razorpay fees",
    "tax": "Tax on fees",
    "refunds": "Refunds",
    "adjustments": "Adjustments",
    "disputes": "Disputes",
    "net_amount": "Net settlement",
}

# Reconciliation tolerance. Exact integer paise arithmetic should agree
# perfectly; a single paise of slack absorbs rounding in upstream sources.
RECONCILE_TOLERANCE_PAISE = 1


@dataclass
class SettlementBreakdown:
    """The result of explaining one settlement row."""

    settlement_id: str
    facts: list[Fact] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reconciles: bool = True
    computed_net: Optional[Money] = None
    reported_net: Optional[Money] = None
    difference: Optional[Money] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing

    def fact_values(self) -> list[str]:
        return [f.value_text for f in self.facts]


def _money(row: dict[str, Any], key: str) -> Optional[Money]:
    """Read a paise field. `None` and absent both mean 'not available'."""
    raw = row.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):  # guard: bool is an int subclass
        return None
    if not isinstance(raw, (int, float)):
        return None
    return Money(int(raw))


def explain_settlement(row: dict[str, Any]) -> SettlementBreakdown:
    """Turn one settlement row into checked, quotable facts."""
    sid = str(row.get("id", "unknown"))
    out = SettlementBreakdown(settlement_id=sid)

    values: dict[str, Optional[Money]] = {k: _money(row, k) for k in _COMPONENTS}
    reported = _money(row, "net_amount")
    out.reported_net = reported

    for key in _COMPONENTS:
        val = values[key]
        if val is None:
            # Disputes/adjustments are commonly absent and mean "none here";
            # gross/fees/tax/refunds being absent is a real information gap.
            if key in ("adjustments", "disputes"):
                values[key] = Money(0)
                continue
            out.missing.append(key)
            continue
        out.facts.append(
            Fact(
                key=key,
                label=_LABELS[key],
                value_text=val.format(),
                source="demo_adapter",
                raw_value=val.rupees,
            )
        )

    if out.missing:
        out.warnings.append(
            "This settlement does not show "
            + ", ".join(_LABELS[m].lower() for m in out.missing)
            + ", so I cannot work out the full breakdown from this screen."
        )
        if reported is not None:
            out.facts.append(
                Fact(
                    key="net_amount",
                    label=_LABELS["net_amount"],
                    value_text=reported.format(),
                    source="demo_adapter",
                    raw_value=reported.rupees,
                )
            )
        out.reconciles = False
        return out

    # Every component is present at this point — `out.missing` was empty above,
    # and the two optional ones were defaulted to zero. Narrowing into a
    # non-optional mapping makes that explicit instead of asserting it.
    complete: dict[str, Money] = {}
    for key in _COMPONENTS:
        value = values[key]
        if value is None:  # unreachable, but never compute money on a guess
            out.warnings.append(f"{_LABELS[key]} went missing while calculating.")
            out.reconciles = False
            return out
        complete[key] = value

    computed = Money(sum(_SIGNS[k] * complete[k].paise for k in _COMPONENTS))
    out.computed_net = computed

    out.facts.append(
        Fact(
            key="computed_net",
            label="Expected settlement",
            value_text=computed.format(),
            source="computed",
            raw_value=computed.rupees,
        )
    )

    if reported is None:
        out.warnings.append(
            "The dashboard does not show a final settlement amount for this row, "
            "so I am showing what the numbers add up to instead."
        )
        out.reconciles = False
        return out

    out.facts.append(
        Fact(
            key="net_amount",
            label=_LABELS["net_amount"],
            value_text=reported.format(),
            source="demo_adapter",
            raw_value=reported.rupees,
        )
    )

    diff = Money(reported.paise - computed.paise)
    out.difference = diff
    out.reconciles = abs(diff.paise) <= RECONCILE_TOLERANCE_PAISE

    if not out.reconciles:
        out.warnings.append(
            f"The parts I can see add up to {computed.format()} but the dashboard "
            f"shows {reported.format()} — a difference of {Money(abs(diff.paise)).format()}. "
            "Something is not visible on this screen, so please check the settlement "
            "report before relying on my breakdown."
        )

    # The headline fact the merchant actually asked about: how much never
    # reached them.
    shortfall = Money(abs(complete["gross_amount"].paise - reported.paise))
    out.facts.append(
        Fact(
            key="shortfall",
            label="Total deducted from gross",
            value_text=shortfall.format(),
            source="computed",
            raw_value=shortfall.rupees,
        )
    )

    return out


def settlement_period_facts(row: dict[str, Any]) -> list[Fact]:
    """Non-money settlement facts (dates, UTR, status)."""
    facts: list[Fact] = []
    start, end = row.get("period_start"), row.get("period_end")
    if start and end:
        text = str(start) if start == end else f"{start} to {end}"
        facts.append(Fact("period", "Settlement period", text, "demo_adapter"))
    if row.get("settled_on"):
        facts.append(Fact("settled_on", "Settled on", str(row["settled_on"]), "demo_adapter"))
    if row.get("status"):
        facts.append(Fact("status", "Status", str(row["status"]), "demo_adapter"))
    if row.get("utr"):
        facts.append(Fact("utr", "UTR", str(row["utr"]), "demo_adapter"))
    return facts


# ── Failed payments ───────────────────────────────────────────────────────────


@dataclass
class FailedPaymentSummary:
    count: int
    total: Optional[Money]
    reasons: dict[str, int] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


def summarise_failed_payments(rows: list[dict[str, Any]]) -> FailedPaymentSummary:
    """Count and total failed payments. Never speculates about retry success."""
    failed = [r for r in rows if str(r.get("status", "")).lower() == "failed"]
    reasons: dict[str, int] = {}
    total_paise = 0
    amounts_known = True

    for r in failed:
        reason = str(r.get("error_reason") or r.get("error_code") or "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
        amt = r.get("amount")
        if isinstance(amt, (int, float)) and not isinstance(amt, bool):
            total_paise += int(amt)
        else:
            amounts_known = False

    total = Money(total_paise) if (failed and amounts_known) else None

    facts = [Fact("failed_count", "Failed payments", str(len(failed)), "demo_adapter",
                  float(len(failed)))]
    if total is not None:
        facts.append(Fact("failed_total", "Value of failed payments", total.format(),
                          "computed", total.rupees))
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        facts.append(Fact(f"reason_{reason}", f"Reason: {_humanise_reason(reason)}",
                          str(n), "demo_adapter", float(n)))

    return FailedPaymentSummary(len(failed), total, reasons, facts, failed)


_REASON_TEXT = {
    "payment_failed": "not completed at the bank",
    "payment_cancelled": "cancelled by the customer",
    "invalid_otp": "wrong OTP entered",
    "insufficient_funds": "not enough balance",
    "unknown": "reason not shown",
}

_REASON_TEXT_HI = {
    "payment_failed": "बैंक पर पूरा नहीं हुआ",
    "payment_cancelled": "ग्राहक ने रद्द कर दिया",
    "invalid_otp": "ग़लत OTP डाला गया",
    "insufficient_funds": "खाते में पैसे कम थे",
    "unknown": "कारण नहीं दिखाया गया",
}

_REASON_TEXT_HINGLISH = {
    "payment_failed": "bank par poora nahi hua",
    "payment_cancelled": "customer ne cancel kar diya",
    "invalid_otp": "galat OTP daala gaya",
    "insufficient_funds": "account mein paise kam the",
    "unknown": "reason nahi dikhaya gaya",
}


def _humanise_reason(reason: str, language: str = "english") -> str:
    """A failure reason in the merchant's own language.

    Leaving these in English inside a Hinglish sentence is exactly the kind of
    half-translated output that makes a tool feel foreign to the people it is
    meant to serve.
    """
    table = {
        "hindi": _REASON_TEXT_HI,
        "hinglish": _REASON_TEXT_HINGLISH,
    }.get(language, _REASON_TEXT)
    return table.get(reason, _REASON_TEXT.get(reason, reason.replace("_", " ")))


# ── Refunds ───────────────────────────────────────────────────────────────────


@dataclass
class RefundSummary:
    full_count: int = 0
    partial_count: int = 0
    total: Optional[Money] = None
    facts: list[Fact] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


def summarise_refunds(rows: list[dict[str, Any]]) -> RefundSummary:
    out = RefundSummary(rows=list(rows))
    total_paise = 0
    known = True
    for r in rows:
        if str(r.get("type", "")).lower() == "partial":
            out.partial_count += 1
        else:
            out.full_count += 1
        amt = r.get("amount")
        if isinstance(amt, (int, float)) and not isinstance(amt, bool):
            total_paise += int(amt)
        else:
            known = False
    out.total = Money(total_paise) if (rows and known) else None

    out.facts = [
        Fact("refund_count", "Refunds", str(len(rows)), "demo_adapter", float(len(rows))),
        Fact("refund_full", "Full refunds", str(out.full_count), "demo_adapter",
             float(out.full_count)),
        Fact("refund_partial", "Partial refunds", str(out.partial_count), "demo_adapter",
             float(out.partial_count)),
    ]
    if out.total is not None:
        out.facts.append(Fact("refund_total", "Total refunded", out.total.format(),
                              "computed", out.total.rupees))
    return out


def refund_amount_check(payment_amount_paise: int, refund_amount_paise: int) -> tuple[bool, str]:
    """Validate a proposed refund. Used by the confirmation flow, never to act."""
    if refund_amount_paise <= 0:
        return False, "A refund has to be more than zero."
    if refund_amount_paise > payment_amount_paise:
        return False, (
            f"{Money(refund_amount_paise).format()} is more than the original payment of "
            f"{Money(payment_amount_paise).format()}. That cannot be refunded."
        )
    if refund_amount_paise == payment_amount_paise:
        return True, "This is a full refund — the customer gets the whole amount back."
    return True, (
        f"This is a partial refund of {Money(refund_amount_paise).format()} out of "
        f"{Money(payment_amount_paise).format()}."
    )
