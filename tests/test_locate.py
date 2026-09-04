"""
"Where is X?" — the point-at-it intent.

This exists because of a real failure during a demo recording: asked
"I didn't see the issue button, can you show me where it is?", Merchant Mode
explained instead of pointing. Worse, "where is the refund button" matched
`refund_tutorial` and delivered a lecture about refunds.

The tests below pin both halves of the fix: locate requests are recognised and
route to pointing, and — just as important — ordinary questions are *not*
stolen by the new rule.
"""

from __future__ import annotations

import asyncio

import pytest

from merchant.audit import AuditLog
from merchant.locate import extract_target, is_locate_request, search_terms
from merchant.models import Intent, Language, ScreenContext, WordBox
from merchant.pipeline import MerchantPipeline, PipelineConfig, PipelineDeps
from merchant.privacy import PrivacyState
from merchant.targeting import resolve_all


def build() -> MerchantPipeline:
    privacy = PrivacyState()
    privacy.grant_permission()
    return MerchantPipeline(PipelineConfig(), PipelineDeps(privacy=privacy,
                                                           audit=AuditLog()))


def ask(pipe: MerchantPipeline, text: str, screen: ScreenContext | None = None):
    return asyncio.run(pipe.ask(text, screen))


# ── Recognising a locate request ──────────────────────────────────────────────


LOCATE_UTTERANCES = [
    "I didn't see the issue button can you show me where it is?",
    "show me where the issue button is",
    "where is the refund button",
    "where can i find the download report button",
    "settlement kahan hai",
    "Refund type column kahan hai",
    "mujhe payment link ka button dikhao",
    "point at the apply filters button",
    "सेटलमेंट कहाँ है",
]

NOT_LOCATE_UTTERANCES = [
    "Kal ke failed payments dikhao",
    "Mere payment ka settlement kam kyon aaya?",
    "Customer ko refund kaise karte hain?",
    "Mujhe payment link banana sikhao",
    "Is screen ko mujhe simple language mein samjhao",
    "What is the settlement period?",
]


@pytest.mark.parametrize("utterance", LOCATE_UTTERANCES)
def test_locate_requests_are_recognised(utterance: str) -> None:
    assert is_locate_request(utterance) is True
    assert extract_target(utterance), f"no target extracted from {utterance!r}"


@pytest.mark.parametrize("utterance", NOT_LOCATE_UTTERANCES)
def test_ordinary_questions_are_not_hijacked(utterance: str) -> None:
    """The new rule must not steal the flows that already worked."""
    assert ask(build(), utterance).intent is not Intent.LOCATE_ELEMENT


@pytest.mark.parametrize("utterance,expected", [
    ("I didn't see the issue button can you show me where it is?", "issue button"),
    ("show me where the issue button is", "issue button"),
    ("where is the refund button", "refund button"),
    ("where can i find the download report button", "download report button"),
    ("settlement kahan hai", "settlement"),
    ("Refund type column kahan hai", "Refund type column"),
])
def test_target_extraction(utterance: str, expected: str) -> None:
    assert extract_target(utterance) == expected


def test_filler_is_stripped_from_the_target() -> None:
    """'I didn't see the X' must yield 'X', not the whole complaint."""
    target = extract_target("I didn't see the issue button can you show me where it is?")
    assert target is not None
    for filler in ("didn't", "see", "show", "where"):
        assert filler not in target.lower()


def test_search_terms_drop_only_the_trailing_ui_noun() -> None:
    # "link" is part of the name here, not a UI noun to discard.
    assert search_terms("payment link button") == ["payment link button", "payment link"]
    assert search_terms("refund button") == ["refund button", "refund"]
    assert search_terms("settlement") == ["settlement"]


def test_a_sentence_is_not_treated_as_a_label() -> None:
    assert extract_target("where is the money that my customers paid me last week "
                          "for all of those grocery orders") is None


# ── The pipeline points rather than explains ──────────────────────────────────


def test_locate_returns_pointing_targets_not_a_tutorial() -> None:
    r = ask(build(), "where is the refund button")

    assert r.intent is Intent.LOCATE_ELEMENT
    assert r.steps == [], "a locate request must not open a tutorial"
    anchors = [t.anchor_text for t in r.highlight_targets]
    assert "refund button" in anchors
    assert "refund" in anchors, "must also try the phrase without its UI noun"


def test_locate_works_for_words_absent_from_the_knowledge_base() -> None:
    """'issue button' appears nowhere in the seed or the KB — it must still point."""
    r = ask(build(), "I didn't see the issue button can you show me where it is?")
    assert r.intent is Intent.LOCATE_ELEMENT
    assert [t.anchor_text for t in r.highlight_targets] == ["issue button", "issue"]


def test_locate_targets_carry_no_coordinates() -> None:
    r = ask(build(), "where is the refund button")
    for target in r.highlight_targets:
        assert target.rect is None


def test_locate_asks_again_when_nothing_was_named() -> None:
    r = ask(build(), "where is it")
    assert r.fallback_used is True
    assert r.highlight_targets == []
    assert "name" in r.answer.lower() or "naam" in r.answer.lower()


@pytest.mark.parametrize("utterance,language", [
    ("where is the refund button", Language.ENGLISH),
    ("Refund type column kahan hai", Language.HINGLISH),
    ("सेटलमेंट कहाँ है", Language.HINDI),
])
def test_locate_answers_in_the_merchants_language(utterance: str,
                                                  language: Language) -> None:
    r = ask(build(), utterance)
    assert r.language is language
    assert r.answer.strip()


# ── Resolution against a real screen ──────────────────────────────────────────


def boxes(rows: list[tuple[str, int, int]]) -> list[WordBox]:
    return [WordBox(t, x, y, 60, 18, confidence=92.0) for t, x, y in rows]


class FakeGeo:
    width, height = 1280, 720
    physical_width, physical_height = 1280, 720
    dpi_scale = 1.0
    logical_left = logical_top = 0


def test_a_named_element_resolves_against_screen_text() -> None:
    """End to end: the spoken phrase finds the word on screen."""
    screen_words = boxes([("Issue", 400, 300), ("Refund", 400, 360),
                          ("Settlements", 100, 120)])
    r = ask(build(), "where is the issue button")

    resolved = resolve_all(r.highlight_targets, geo=FakeGeo(),
                           word_boxes=screen_words, dom_map={})
    found = [x for x in resolved if x.found]
    assert found, "should have located 'Issue' on screen"
    assert found[0].x == pytest.approx(400.0)
    assert found[0].y == pytest.approx(300.0)


def test_unfindable_element_is_reported_not_guessed() -> None:
    screen_words = boxes([("Settlements", 100, 120), ("Payments", 100, 160)])
    r = ask(build(), "where is the issue button")

    resolved = resolve_all(r.highlight_targets, geo=FakeGeo(),
                           word_boxes=screen_words, dom_map={})
    assert all(not x.found for x in resolved)
    assert all(x.x == 0.0 and x.y == 0.0 for x in resolved)
