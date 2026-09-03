"""
Comprehensive tests for merchant.facts module.

Tests the fact extraction and settlement reconciliation logic.
"""

import pytest
from merchant.adapters.demo import DemoAdapter
from merchant.facts import (
    explain_settlement,
    summarise_failed_payments,
    summarise_refunds,
    refund_amount_check,
)
from merchant.models import Money


class TestMoney:
    """Tests for Money value object."""

    def test_from_rupees_integer(self):
        """Money.from_rupees with integer input."""
        m = Money.from_rupees(100)
        assert m.paise == 10000
        assert m.rupees == 100.0

    def test_from_rupees_float(self):
        """Money.from_rupees with float input."""
        m = Money.from_rupees(100.50)
        assert m.paise == 10050
        assert m.rupees == 100.50

    def test_from_rupees_string(self):
        """Money.from_rupees with string input."""
        m = Money.from_rupees("100.25")
        assert m.paise == 10025
        assert m.rupees == 100.25

    def test_from_rupees_rounding(self):
        """Money.from_rupees rounds half-up."""
        m = Money.from_rupees(100.125)
        assert m.paise == 10013  # 100.125 * 100 = 10012.5, rounded up to 10013

    def test_format_no_paise(self):
        """format() on amount with no paise portion."""
        m = Money(926400)
        formatted = m.format()
        assert formatted == "₹9,264"

    def test_format_with_paise(self):
        """format() on amount with paise portion."""
        m = Money(12345678)
        formatted = m.format()
        assert formatted == "₹1,23,456.78"

    def test_format_indian_grouping_large(self):
        """format() with Indian digit grouping for large amounts."""
        m = Money(123456789)
        formatted = m.format()
        assert formatted == "₹12,34,567.89"

    def test_format_negative(self):
        """format() preserves sign for negative amounts."""
        m = Money(-926400)
        formatted = m.format()
        assert formatted == "-₹9,264"

    def test_format_small_amount(self):
        """format() for amounts less than 100."""
        m = Money(50)
        formatted = m.format()
        assert formatted == "₹0.50"

    def test_money_addition(self):
        """Money addition works correctly."""
        m1 = Money(1000)
        m2 = Money(2000)
        result = m1 + m2
        assert result.paise == 3000

    def test_money_subtraction(self):
        """Money subtraction works correctly."""
        m1 = Money(3000)
        m2 = Money(1000)
        result = m1 - m2
        assert result.paise == 2000

    def test_money_currency_mismatch_raises(self):
        """Addition with mismatched currencies raises error."""
        m1 = Money(1000, "INR")
        m2 = Money(1000, "USD")
        with pytest.raises(ValueError):
            _ = m1 + m2


class TestSettlementExplanation:
    """Tests for explain_settlement function."""

    @pytest.fixture
    def demo_adapter(self):
        """Provide demo adapter with settlement_lower_than_gross scenario."""
        return DemoAdapter(scenario_id="settlement_lower_than_gross")

    def test_settlement_complete_and_reconciles(self, demo_adapter):
        """First settlement row: complete, reconciles, has correct computed_net."""
        settlements = demo_adapter.settlements().rows
        assert len(settlements) > 0
        first = settlements[0]

        result = explain_settlement(first)

        # The settlement should be complete (no missing fields)
        assert result.complete is True
        assert result.missing == []

        # Should reconcile
        assert result.reconciles is True

        # computed_net should be 926400 paise
        assert result.computed_net is not None
        assert result.computed_net.paise == 926400

        # Shortfall fact should exist with value ₹736
        shortfall_fact = next((f for f in result.facts if f.key == "shortfall"), None)
        assert shortfall_fact is not None
        assert shortfall_fact.value_text == "₹736"

    def test_settlement_with_missing_fees(self):
        """Settlement with fees=None: incomplete, reconciles=False."""
        adapter = DemoAdapter(scenario_id="incomplete_data")
        settlements = adapter.settlements().rows
        assert len(settlements) > 0
        row = settlements[0]

        result = explain_settlement(row)

        # Should be incomplete
        assert result.complete is False
        assert "fees" in result.missing
        assert "tax" in result.missing

        # Should not reconcile
        assert result.reconciles is False

        # Should have warning about breakdown
        assert any("cannot work out the full breakdown" in w for w in result.warnings)

        # Critically: no fact should have raw_value == 0 for fees
        for fact in result.facts:
            if fact.key == "fees":
                pytest.fail("fees should not appear as a fact when missing")

    def test_settlement_disagreement(self):
        """Settlement where net doesn't match computed: reconciles=False."""
        # Build a hand-crafted row with disagreement
        row = {
            "id": "test_disagreement",
            "gross_amount": 1000000,
            "fees": 20000,
            "tax": 3600,
            "refunds": 50000,
            "adjustments": 0,
            "disputes": 0,
            "net_amount": 900000,  # Wrong! Should be 926400
        }

        result = explain_settlement(row)

        # Should not reconcile
        assert result.reconciles is False

        # Should have warning mentioning the difference
        assert any("difference" in w.lower() for w in result.warnings)


class TestFailedPaymentSummary:
    """Tests for summarise_failed_payments function."""

    @pytest.fixture
    def demo_adapter(self):
        """Provide demo adapter with multiple_failed_payments scenario."""
        return DemoAdapter(scenario_id="multiple_failed_payments")

    def test_failed_payments_count_and_total(self, demo_adapter):
        """multiple_failed_payments scenario: count=4, total computed correctly."""
        payments = demo_adapter.payments(status="failed").rows
        assert len(payments) >= 4

        result = summarise_failed_payments(payments[:4])

        # Count should be 4
        assert result.count == 4

        # Total should be sum of the 4 amounts
        total_paise = sum(p.get("amount", 0) for p in payments[:4] if isinstance(p.get("amount"), (int, float)))
        expected_total = Money(total_paise)
        assert result.total == expected_total

    def test_failed_payments_reasons(self, demo_adapter):
        """Failed payments have distinct reasons in summary."""
        payments = demo_adapter.payments(status="failed").rows
        result = summarise_failed_payments(payments)

        # Reasons should be a dict with reason codes
        assert isinstance(result.reasons, dict)
        assert len(result.reasons) > 0

        # All reason keys should be strings
        for reason_key in result.reasons.keys():
            assert isinstance(reason_key, str)


class TestRefundSummary:
    """Tests for summarise_refunds function."""

    @pytest.fixture
    def demo_adapter(self):
        """Provide demo adapter with full_and_partial_refunds scenario."""
        return DemoAdapter(scenario_id="full_and_partial_refunds")

    def test_refund_full_and_partial_count(self, demo_adapter):
        """full_and_partial_refunds scenario: 1 full, 1 partial."""
        refunds = demo_adapter.refunds().rows
        assert len(refunds) >= 2

        result = summarise_refunds(refunds)

        # Should have 1 full refund
        assert result.full_count == 1

        # Should have 1 partial refund
        assert result.partial_count == 1


class TestRefundAmountCheck:
    """Tests for refund_amount_check function."""

    def test_refund_over_amount_rejected(self):
        """Over-refund is rejected."""
        payment_amount = 100000  # ₹1000
        refund_amount = 150000   # ₹1500 (too much!)

        ok, msg = refund_amount_check(payment_amount, refund_amount)
        assert ok is False
        assert "more than the original payment" in msg

    def test_refund_zero_rejected(self):
        """Zero refund is rejected."""
        payment_amount = 100000
        refund_amount = 0

        ok, msg = refund_amount_check(payment_amount, refund_amount)
        assert ok is False
        assert "more than zero" in msg

    def test_refund_negative_rejected(self):
        """Negative refund is rejected."""
        payment_amount = 100000
        refund_amount = -50000

        ok, msg = refund_amount_check(payment_amount, refund_amount)
        assert ok is False

    def test_refund_exact_amount_full_refund(self):
        """Refund of exact amount is marked as full refund."""
        payment_amount = 100000
        refund_amount = 100000

        ok, msg = refund_amount_check(payment_amount, refund_amount)
        assert ok is True
        assert "full refund" in msg.lower()

    def test_refund_partial_amount(self):
        """Partial refund less than full amount."""
        payment_amount = 100000
        refund_amount = 50000

        ok, msg = refund_amount_check(payment_amount, refund_amount)
        assert ok is True
        assert "partial refund" in msg.lower()
