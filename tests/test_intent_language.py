"""
Comprehensive tests for merchant.intent module.

Tests language detection and intent classification.
"""

import pytest
from merchant.intent import detect_language, detect_intent
from merchant.models import Intent, Language


class TestLanguageDetection:
    """Tests for detect_language function."""

    def test_pure_devanagari_is_hindi(self):
        """Pure Devanagari text is classified as HINDI."""
        text = "मेरे सेटलमेंट में कम पैसा क्यों आया?"
        result = detect_language(text)
        assert result is Language.HINDI

    def test_hinglish_mixed_script(self):
        """Devanagari word inside English sentence is HINGLISH."""
        text = "Mere payment ka settlement kam kyon aaya?"
        result = detect_language(text)
        assert result is Language.HINGLISH

    def test_english_only(self):
        """Pure English text is classified as ENGLISH."""
        text = "Why is my settlement lower than my sales?"
        result = detect_language(text)
        assert result is Language.ENGLISH

    def test_hindi_word_in_english_hinglish(self):
        """Devanagari word inside English text is HINGLISH."""
        text = "My payment का settlement is low"
        result = detect_language(text)
        assert result is Language.HINGLISH

    def test_empty_string_defaults_to_english(self):
        """Empty string defaults to ENGLISH."""
        result = detect_language("")
        assert result is Language.ENGLISH

    def test_whitespace_only_defaults_to_english(self):
        """Whitespace-only string defaults to ENGLISH."""
        result = detect_language("   ")
        assert result is Language.ENGLISH


class TestIntentDetection:
    """Tests for detect_intent function."""

    @pytest.mark.parametrize("text,expected_intent", [
        ("Mere payment ka settlement kam kyon aaya?", Intent.EXPLAIN_SETTLEMENT),
        ("Why did I receive less money than I collected?", Intent.EXPLAIN_SETTLEMENT),
        ("Kal ke failed payments dikhao", Intent.SHOW_FAILED_PAYMENTS),
        ("Show me yesterday's failed payments", Intent.SHOW_FAILED_PAYMENTS),
        ("Mujhe payment link banana sikhao", Intent.CREATE_PAYMENT_LINK_TUTORIAL),
        ("Customer ko refund kaise karte hain?", Intent.REFUND_TUTORIAL),
        ("Refund aur reversal mein kya difference hai?", Intent.EXPLAIN_TERM),
        ("Is screen ko mujhe simple language mein samjhao", Intent.EXPLAIN_SCREEN),
        ("next", Intent.NEXT_STEP),
        ("Tell me about the weather outside", Intent.UNKNOWN),
    ])
    def test_intent_detection_parametrized(self, text, expected_intent):
        """Detect intent for various test cases."""
        result = detect_intent(text)
        assert result.intent == expected_intent

    def test_confidence_in_valid_range(self):
        """Detected confidence is in [0.0, 1.0]."""
        result = detect_intent("settlement kam kyon aaya")
        assert 0.0 <= result.confidence <= 1.0

    def test_unknown_returns_confidence_zero(self):
        """Unknown intent returns confidence near 0."""
        result = detect_intent("zzzq flurble wumpus")
        assert result.intent == Intent.UNKNOWN
        assert result.confidence == 0.0

    def test_settlement_hinglish(self):
        """Settlement inquiry in Hinglish is detected."""
        result = detect_intent("Mere payment ka settlement kam kyon aaya?")
        assert result.intent == Intent.EXPLAIN_SETTLEMENT
        assert result.language is Language.HINGLISH

    def test_failed_payments_english(self):
        """Failed payments query in English is detected."""
        result = detect_intent("Show me yesterday's failed payments")
        assert result.intent == Intent.SHOW_FAILED_PAYMENTS
        assert result.language is Language.ENGLISH

    def test_next_step_exact(self):
        """'next' by itself is detected as NEXT_STEP."""
        result = detect_intent("next")
        assert result.intent == Intent.NEXT_STEP

    def test_next_step_with_punctuation(self):
        """'next!' or 'next?' is detected as NEXT_STEP."""
        for text in ["next!", "next?", "Next."]:
            result = detect_intent(text)
            assert result.intent == Intent.NEXT_STEP

    def test_refund_vs_reversal_term_explanation(self):
        """Refund vs reversal is detected as EXPLAIN_TERM."""
        result = detect_intent("Refund aur reversal mein kya difference hai?")
        assert result.intent == Intent.EXPLAIN_TERM

    def test_explain_screen_intent(self):
        """Screen explanation request detected."""
        result = detect_intent("Is screen ko mujhe simple language mein samjhao")
        assert result.intent == Intent.EXPLAIN_SCREEN

    def test_create_payment_link_tutorial(self):
        """Payment link creation tutorial detected."""
        result = detect_intent("Mujhe payment link banana sikhao")
        assert result.intent == Intent.CREATE_PAYMENT_LINK_TUTORIAL

    def test_confidence_increases_with_specificity(self):
        """More specific settlement query has higher confidence."""
        vague = detect_intent("settlement")
        specific = detect_intent("settlement kam kyon aaya")
        assert specific.confidence >= vague.confidence

    def test_matched_patterns_recorded(self):
        """Matched patterns are recorded in detection result."""
        result = detect_intent("settlement kam kyon aaya")
        assert len(result.matched) > 0

    def test_empty_string_returns_unknown(self):
        """Empty string returns UNKNOWN intent."""
        result = detect_intent("")
        assert result.intent == Intent.UNKNOWN
        assert result.confidence == 0.0

    def test_topic_hint_for_settlement(self):
        """Settlement queries hint at settlement topic."""
        result = detect_intent("settlement lower than expected")
        assert result.topic_hint == "settlements"

    def test_topic_hint_for_refund(self):
        """Refund queries hint at refund topic."""
        result = detect_intent("refund vs reversal")
        assert result.topic_hint == "refunds"

    def test_hindi_settlement_query(self):
        """Hindi settlement query is detected correctly."""
        result = detect_intent("मेरे settlement में कम पैसा क्यों आया?")
        assert result.intent == Intent.EXPLAIN_SETTLEMENT
        assert result.language is Language.HINDI
        assert result.confidence > 0.0
