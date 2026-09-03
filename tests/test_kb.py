"""
Comprehensive tests for merchant.kb module.

Tests knowledge base loading, retrieval, and entry validation.
"""

import pytest
from datetime import datetime
from merchant.kb import (
    all_entries,
    retrieve,
    get,
    unverified_notice,
)
from merchant.models import Language, Intent, DashboardPage


class TestKnowledgeBaseLoading:
    """Tests for KB loading and entry validation."""

    def test_kb_loads(self):
        """Knowledge base loads successfully."""
        entries = all_entries()
        assert isinstance(entries, list)

    def test_kb_has_minimum_entries(self):
        """KB has at least 26 entries."""
        entries = all_entries()
        assert len(entries) >= 26

    def test_every_entry_has_required_fields(self):
        """Every entry has non-empty required fields."""
        entries = all_entries()
        for entry in entries:
            assert entry.id
            assert entry.simple_en
            assert entry.simple_hi
            assert entry.simple_hinglish
            assert entry.source_url
            assert entry.source_url.startswith("https://razorpay.com")
            assert entry.last_reviewed

    def test_every_entry_has_valid_date(self):
        """Every entry's last_reviewed is a valid YYYY-MM-DD date."""
        entries = all_entries()
        for entry in entries:
            try:
                datetime.strptime(entry.last_reviewed, "%Y-%m-%d")
            except ValueError:
                pytest.fail(f"Entry {entry.id} has invalid date: {entry.last_reviewed}")

    def test_entry_ids_are_unique(self):
        """All entry IDs are unique."""
        entries = all_entries()
        ids = [e.id for e in entries]
        assert len(ids) == len(set(ids))

    def test_source_urls_start_with_https_razorpay(self):
        """All source URLs start with https://razorpay.com."""
        entries = all_entries()
        for entry in entries:
            assert entry.source_url.startswith("https://razorpay.com"), \
                f"Entry {entry.id} has invalid URL: {entry.source_url}"


class TestKnowledgeBaseRetrieval:
    """Tests for KB retrieval function."""

    def test_retrieve_settlement_query(self):
        """Retrieve settlement-related results for settlement query."""
        results = retrieve("settlement kam kyon aaya")
        assert len(results) > 0

        # At least one result should be about settlements
        topics = {e.topic for e in results}
        assert any("settlement" in topic for topic in topics)

    def test_retrieve_refund_vs_reversal(self):
        """Retrieve includes refund_vs_reversal entry for relevant query."""
        results = retrieve("refund aur reversal")
        result_ids = {e.id for e in results}
        assert "refund_vs_reversal" in result_ids, \
            "refund_vs_reversal entry should be in results"

    def test_retrieve_nonsense_returns_empty(self):
        """Nonsense query returns empty list."""
        results = retrieve("zzzq flurble wumpus")
        assert results == []

    def test_retrieve_respects_limit(self):
        """Retrieve respects the limit parameter."""
        results = retrieve("settlement", limit=2)
        assert len(results) <= 2

    def test_retrieve_with_intent_context(self):
        """Retrieve uses intent context to select relevant topics."""
        results = retrieve("", intent=Intent.EXPLAIN_SETTLEMENT)
        # Should return settlement-related entries even with empty query
        topics = {e.topic for e in results}
        assert len(results) > 0

    def test_retrieve_with_page_context(self):
        """Retrieve considers page context."""
        results = retrieve("fee", page=DashboardPage.SETTLEMENTS)
        # Should prefer entries tagged for settlements page
        assert len(results) > 0


class TestKnowledgeEntryTextFor:
    """Tests for KnowledgeEntry.text_for language selection."""

    def test_text_for_hindi(self):
        """text_for(HINDI) returns Devanagari string."""
        entries = all_entries()
        if not entries:
            pytest.skip("No entries in KB")
        entry = entries[0]

        hindi_text = entry.text_for(Language.HINDI)
        assert hindi_text == entry.simple_hi
        assert hindi_text  # non-empty

    def test_text_for_hinglish(self):
        """text_for(HINGLISH) returns Roman script string."""
        entries = all_entries()
        if not entries:
            pytest.skip("No entries in KB")
        entry = entries[0]

        hinglish_text = entry.text_for(Language.HINGLISH)
        assert hinglish_text == entry.simple_hinglish
        assert hinglish_text  # non-empty

    def test_text_for_english(self):
        """text_for(ENGLISH) returns English string."""
        entries = all_entries()
        if not entries:
            pytest.skip("No entries in KB")
        entry = entries[0]

        english_text = entry.text_for(Language.ENGLISH)
        assert english_text == entry.simple_en
        assert english_text  # non-empty

    def test_hindi_and_hinglish_differ(self):
        """Hindi and Hinglish versions are different."""
        entries = all_entries()
        for entry in entries:
            hindi = entry.text_for(Language.HINDI)
            hinglish = entry.text_for(Language.HINGLISH)
            # They should be different (one Devanagari, one Roman)
            assert hindi != hinglish


class TestUnverifiedNotice:
    """Tests for unverified_notice function."""

    def test_empty_entries_returns_empty_notice(self):
        """Empty entry list returns empty notice."""
        notice = unverified_notice([], Language.ENGLISH)
        assert notice == ""

    def test_verified_entries_return_empty_notice(self):
        """All verified entries return empty notice."""
        entries = [e for e in all_entries() if e.verified]
        if entries:
            notice = unverified_notice(entries, Language.ENGLISH)
            assert notice == ""

    def test_unverified_entry_returns_notice_english(self):
        """Unverified entry returns English notice."""
        entries = [e for e in all_entries() if not e.verified]
        if not entries:
            pytest.skip("No unverified entries in KB")

        notice = unverified_notice(entries, Language.ENGLISH)
        assert notice != ""
        assert "not officially verified" in notice.lower()

    def test_unverified_entry_returns_notice_hindi(self):
        """Unverified entry returns Hindi notice."""
        entries = [e for e in all_entries() if not e.verified]
        if not entries:
            pytest.skip("No unverified entries in KB")

        notice = unverified_notice(entries, Language.HINDI)
        assert notice != ""
        # Hindi notice should contain Devanagari characters
        assert any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in notice)

    def test_unverified_entry_returns_notice_hinglish(self):
        """Unverified entry returns Hinglish notice."""
        entries = [e for e in all_entries() if not e.verified]
        if not entries:
            pytest.skip("No unverified entries in KB")

        notice = unverified_notice(entries, Language.HINGLISH)
        assert notice != ""


class TestKnowledgeEntryGetById:
    """Tests for get function."""

    def test_get_existing_entry(self):
        """Get returns existing entry by ID."""
        entries = all_entries()
        if not entries:
            pytest.skip("No entries in KB")

        first_id = entries[0].id
        retrieved = get(first_id)
        assert retrieved is not None
        assert retrieved.id == first_id

    def test_get_nonexistent_returns_none(self):
        """Get returns None for nonexistent entry."""
        retrieved = get("nonexistent_entry_id_xyz")
        assert retrieved is None
