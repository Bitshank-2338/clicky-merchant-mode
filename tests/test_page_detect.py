"""
Comprehensive tests for merchant.page_detect module.

Tests dashboard page detection from various signals.
"""

import pytest
from merchant.page_detect import detect_page
from merchant.models import DashboardPage, ScreenContext


class TestPageDetectionFromDOM:
    """Tests for page detection via DOM map."""

    def test_dom_map_settlement_target(self):
        """DOM map with settlement target → SETTLEMENTS page."""
        ctx = ScreenContext(
            dom_map={"settlement.gross_amount": (0, 0, 10, 10)}
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.SETTLEMENTS
        assert result.signal == "dom_map"
        assert result.confidence > 0.9

    def test_dom_map_payment_target(self):
        """DOM map with payment target → PAYMENTS page."""
        ctx = ScreenContext(
            dom_map={"payments.date_filter": (0, 0, 10, 10)}
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.PAYMENTS
        assert result.signal == "dom_map"

    def test_dom_map_refund_target(self):
        """DOM map with refund target → REFUNDS page."""
        ctx = ScreenContext(
            dom_map={"refunds.table": (0, 0, 10, 10)}
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.REFUNDS
        assert result.signal == "dom_map"

    def test_dom_map_link_target(self):
        """DOM map with link target → PAYMENT_LINKS page."""
        ctx = ScreenContext(
            dom_map={"link.amount": (0, 0, 10, 10)}
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.PAYMENT_LINKS
        assert result.signal == "dom_map"

    def test_nav_only_does_not_determine_page(self):
        """DOM map with only nav.* keys does not determine page."""
        ctx = ScreenContext(
            dom_map={
                "nav.payments": (0, 0, 10, 10),
                "nav.settlements": (0, 0, 10, 10),
                "nav.refunds": (0, 0, 10, 10),
            }
        )
        result = detect_page(ctx)
        # nav.* alone should not determine the page
        assert result.page == DashboardPage.UNKNOWN or result.signal != "dom_map"


class TestPageDetectionFromURL:
    """Tests for page detection via URL hint."""

    def test_url_payment_links(self):
        """URL containing 'payment-links' → PAYMENT_LINKS."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/payment-links"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.PAYMENT_LINKS
        assert result.signal == "url"
        assert result.confidence > 0.9

    def test_url_settlements(self):
        """URL containing 'settlements' → SETTLEMENTS."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/settlements"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.SETTLEMENTS
        assert result.signal == "url"

    def test_url_refunds(self):
        """URL containing 'refunds' → REFUNDS."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/refunds"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.REFUNDS
        assert result.signal == "url"

    def test_url_payments(self):
        """URL containing 'payments' → PAYMENTS."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/payments"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.PAYMENTS
        assert result.signal == "url"

    def test_url_reports(self):
        """URL containing 'reports' → REPORTS."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/reports"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.REPORTS
        assert result.signal == "url"


class TestPageDetectionFromOCR:
    """Tests for page detection via OCR text."""

    def test_ocr_settlement_keywords(self):
        """OCR text with settlement keywords → SETTLEMENTS."""
        ctx = ScreenContext(
            ocr_text="Settlement Period Gross Amount Net Settlement"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.SETTLEMENTS
        assert result.signal == "ocr"
        assert result.confidence < 0.9  # OCR is uncertain

    def test_ocr_refund_keywords(self):
        """OCR text with refund keywords → REFUNDS."""
        ctx = ScreenContext(
            ocr_text="Refund ID Refund Type Partial Processed"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.REFUNDS
        assert result.signal == "ocr"

    def test_ocr_payment_link_keywords(self):
        """OCR text with payment link keywords → PAYMENT_LINKS."""
        ctx = ScreenContext(
            ocr_text="Create Payment Link Expire By Short URL"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.PAYMENT_LINKS
        assert result.signal == "ocr"

    def test_ocr_nonsense_returns_unknown(self):
        """OCR text with no relevant keywords → UNKNOWN."""
        ctx = ScreenContext(
            ocr_text="zzzq flurble wumpus xyz"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.UNKNOWN
        assert result.signal == "ocr"

    def test_ocr_ambiguous_text_low_confidence(self):
        """Ambiguous OCR text yields low confidence or UNKNOWN."""
        ctx = ScreenContext(
            ocr_text="Payments Refunds Settlement"
        )
        result = detect_page(ctx)
        # Should either be UNKNOWN or have low confidence
        assert result.confidence < 0.6 or result.page == DashboardPage.UNKNOWN


class TestPageDetectionPriority:
    """Tests for signal priority (DOM > URL > OCR)."""

    def test_dom_overrides_url(self):
        """DOM map takes priority over URL."""
        ctx = ScreenContext(
            dom_map={"settlement.gross_amount": (0, 0, 10, 10)},
            url_hint="https://dashboard.razorpay.com/app/payments"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.SETTLEMENTS
        assert result.signal == "dom_map"

    def test_url_overrides_ocr(self):
        """URL takes priority over OCR."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/payment-links",
            ocr_text="Settlement Gross Amount Net Settlement"
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.PAYMENT_LINKS
        assert result.signal == "url"


class TestEmptyScreenContext:
    """Tests for empty screen context."""

    def test_empty_context_returns_unknown(self):
        """Empty ScreenContext → UNKNOWN page."""
        ctx = ScreenContext()
        result = detect_page(ctx)
        assert result.page == DashboardPage.UNKNOWN
        assert result.confidence == 0.0
        assert result.signal == "none"

    def test_whitespace_text_treated_as_empty(self):
        """Whitespace-only OCR text treated as empty."""
        ctx = ScreenContext(
            ocr_text="   \n\t  "
        )
        result = detect_page(ctx)
        assert result.page == DashboardPage.UNKNOWN


class TestConfidenceValues:
    """Tests for confidence value ranges."""

    def test_dom_confidence_very_high(self):
        """DOM detection has very high confidence."""
        ctx = ScreenContext(
            dom_map={"settlement.gross_amount": (0, 0, 10, 10)}
        )
        result = detect_page(ctx)
        assert result.confidence > 0.9

    def test_url_confidence_high(self):
        """URL detection has high confidence."""
        ctx = ScreenContext(
            url_hint="https://dashboard.razorpay.com/app/settlements"
        )
        result = detect_page(ctx)
        assert result.confidence > 0.8

    def test_ocr_confidence_lower(self):
        """OCR detection typically has lower confidence."""
        ctx = ScreenContext(
            ocr_text="Settlement Gross Amount Net Settlement"
        )
        result = detect_page(ctx)
        assert result.confidence < 0.9

    def test_confidence_in_valid_range(self):
        """All confidence values are in [0.0, 1.0]."""
        contexts = [
            ScreenContext(),
            ScreenContext(ocr_text="settlement"),
            ScreenContext(url_hint="https://dashboard.razorpay.com/app/payments"),
            ScreenContext(dom_map={"settlement.gross_amount": (0, 0, 10, 10)}),
        ]
        for ctx in contexts:
            result = detect_page(ctx)
            assert 0.0 <= result.confidence <= 1.0
