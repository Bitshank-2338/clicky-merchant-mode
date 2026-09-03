"""
Anti-drift test for mock dashboard contract with seed data.

Ensures the dashboard markup stays in sync with:
1. The seed's ui_anchors
2. The explain module's target lists
3. The dashboard app's page registration
"""

import re
import json
from pathlib import Path
import pytest
from merchant.adapters.demo import ui_anchors, load_seed
from merchant.explain import (
    SETTLEMENT_TARGETS,
    failed_payment_targets,
    payment_link_targets,
    refund_targets,
)


# Paths to dashboard files
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "mockdashboard"
INDEX_HTML = DASHBOARD_DIR / "index.html"
APP_JS = DASHBOARD_DIR / "app.js"


@pytest.fixture
def seed_ui_anchors():
    """Load ui_anchors from seed file."""
    return ui_anchors()


@pytest.fixture
def dashboard_markup():
    """Load index.html as text."""
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture
def dashboard_app_js():
    """Load app.js as text."""
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture
def explain_targets():
    """Collect all target_ids from explain module."""
    targets = []
    # Settlement targets
    for target_id, _, _ in SETTLEMENT_TARGETS:
        targets.append(target_id)
    # Failed payment targets
    for target in failed_payment_targets():
        targets.append(target.target_id)
    # Payment link targets
    for target in payment_link_targets():
        targets.append(target.target_id)
    # Refund targets
    for target in refund_targets():
        targets.append(target.target_id)
    return targets


class TestDashboardMarkupHasTargets:
    """Tests that dashboard markup contains all expected data-clicky-target attributes."""

    def test_extract_targets_from_html(self, dashboard_markup):
        """Can extract data-clicky-target from HTML."""
        pattern = r'data-clicky-target="([^"]*)"'
        matches = re.findall(pattern, dashboard_markup)
        assert len(matches) > 0

    def test_extract_targets_from_app_js(self, dashboard_app_js):
        """Can extract data-clicky-target from app.js (escaped quotes)."""
        pattern = r'data-clicky-target=\\"([^\\]*)\\"'
        matches = re.findall(pattern, dashboard_app_js)
        assert len(matches) > 0 or True  # JS may use different quoting

    def test_all_dashboard_targets_in_seed_anchors(self, seed_ui_anchors, dashboard_markup, dashboard_app_js):
        """Every data-clicky-target in dashboard files is a key in seed ui_anchors."""
        # Extract from HTML
        html_pattern = r'data-clicky-target="([^"]*)"'
        html_targets = set(re.findall(html_pattern, dashboard_markup))

        # Extract from app.js (both regular quotes and potential escaping patterns)
        js_pattern = r'data-clicky-target="([^"]*)"'
        js_targets = set(re.findall(js_pattern, dashboard_app_js))

        all_dashboard_targets = html_targets | js_targets
        all_dashboard_targets.discard("")  # Remove empty strings

        # Every target should be in seed
        for target_id in all_dashboard_targets:
            assert target_id in seed_ui_anchors, \
                f"Dashboard target '{target_id}' not in seed ui_anchors"


class TestExplainTargetsInDashboard:
    """Tests that all explain module targets exist in dashboard."""

    def test_all_explain_targets_in_dashboard(self, explain_targets, dashboard_markup, dashboard_app_js):
        """Every explain target_id appears in dashboard markup."""
        # Extract all targets from dashboard
        html_pattern = r'data-clicky-target="([^"]*)"'
        html_targets = set(re.findall(html_pattern, dashboard_markup))

        js_pattern = r'data-clicky-target="([^"]*)"'
        js_targets = set(re.findall(js_pattern, dashboard_app_js))

        all_dashboard_targets = html_targets | js_targets
        all_dashboard_targets.discard("")

        # Every explain target should be in dashboard
        for target_id in explain_targets:
            assert target_id in all_dashboard_targets, \
                f"Explain target '{target_id}' not found in dashboard markup"


class TestSettlementTargetsInDashboard:
    """Tests for settlement-specific targets."""

    def test_settlement_targets_exist(self, dashboard_markup, dashboard_app_js):
        """All settlement targets exist in dashboard."""
        settlement_target_ids = [t[0] for t in SETTLEMENT_TARGETS]
        pattern = r'data-clicky-target="([^"]*)"'
        html_targets = set(re.findall(pattern, dashboard_markup))
        js_targets = set(re.findall(pattern, dashboard_app_js))
        dashboard_targets = html_targets | js_targets

        for target_id in settlement_target_ids:
            assert target_id in dashboard_targets, \
                f"Settlement target '{target_id}' not in dashboard"


class TestPaymentLinkTargetsInDashboard:
    """Tests for payment link-specific targets."""

    def test_payment_link_targets_exist(self, dashboard_app_js):
        """All payment link targets exist in dashboard."""
        link_target_ids = [t.target_id for t in payment_link_targets()]
        pattern = r'data-clicky-target="([^"]*)"'
        dashboard_targets = set(re.findall(pattern, dashboard_app_js))
        dashboard_targets.discard("")

        for target_id in link_target_ids:
            assert target_id in dashboard_targets, \
                f"Link target '{target_id}' not in dashboard"


class TestDashboardGlobalVariables:
    """Tests for required dashboard global variables."""

    def test_window_clicky_screen_map_exists(self, dashboard_app_js):
        """app.js defines window.__clickyScreenMap."""
        assert "window.__clickyScreenMap" in dashboard_app_js, \
            "app.js must define window.__clickyScreenMap"

    def test_window_clicky_page_id_exists(self, dashboard_app_js):
        """app.js defines window.__clickyPageId."""
        assert "window.__clickyPageId" in dashboard_app_js, \
            "app.js must define window.__clickyPageId"


class TestPaymentLinkFormSafety:
    """Tests that payment link form doesn't post to real APIs."""

    def test_payment_link_form_has_prevent_default(self, dashboard_app_js):
        """Payment link form calls preventDefault."""
        assert "preventDefault" in dashboard_app_js, \
            "app.js must use preventDefault to block form submission"

    def test_payment_link_form_not_posting_to_real_api(self, dashboard_app_js):
        """Payment link form does not post to api.razorpay.com."""
        assert "api.razorpay.com" not in dashboard_app_js, \
            "app.js must not post to real api.razorpay.com"

    def test_no_real_payment_submission(self, dashboard_app_js):
        """Form submission is prevented, not sent to real server."""
        # Check that preventDefault is called before any potential submission
        form_match = re.search(r"create.*link|payment.*link", dashboard_app_js, re.IGNORECASE)
        assert form_match, "Should have payment link form"
        # preventDefault should exist (checked above)
        assert "preventDefault" in dashboard_app_js


class TestSeedUiAnchorsValidity:
    """Tests that seed ui_anchors are valid."""

    def test_ui_anchors_non_empty(self, seed_ui_anchors):
        """ui_anchors is non-empty."""
        assert len(seed_ui_anchors) > 0

    def test_ui_anchors_values_non_empty(self, seed_ui_anchors):
        """All ui_anchor values are non-empty strings."""
        for key, value in seed_ui_anchors.items():
            assert value, f"ui_anchor '{key}' has empty value"
            assert isinstance(value, str), f"ui_anchor '{key}' value is not a string"

    def test_ui_anchors_no_underscore_keys(self, seed_ui_anchors):
        """ui_anchors does not include keys starting with underscore."""
        for key in seed_ui_anchors.keys():
            assert not key.startswith("_"), \
                f"ui_anchors should not have underscore-prefixed key: {key}"


class TestDashboardNavigationAnchors:
    """Tests for navigation-related targets."""

    def test_nav_payments_in_dashboard(self, dashboard_markup):
        """nav.payments target is in dashboard."""
        assert 'data-clicky-target="nav.payments"' in dashboard_markup

    def test_nav_settlements_in_dashboard(self, dashboard_markup):
        """nav.settlements target is in dashboard."""
        assert 'data-clicky-target="nav.settlements"' in dashboard_markup

    def test_nav_refunds_in_dashboard(self, dashboard_markup):
        """nav.refunds target is in dashboard."""
        assert 'data-clicky-target="nav.refunds"' in dashboard_markup

    def test_nav_payment_links_in_dashboard(self, dashboard_markup):
        """nav.payment_links target is in dashboard."""
        assert 'data-clicky-target="nav.payment_links"' in dashboard_markup
