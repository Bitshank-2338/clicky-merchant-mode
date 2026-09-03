"""
Highlight-targeting tests.

The rule under test: Clicky points at something only when it actually located
it. A confidently wrong arrow on a payments screen is worse than no arrow, so
"not found" must be a first-class, well-behaved outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from merchant.models import HighlightTarget, TargetStrategy, WordBox
from merchant.ocr_boxes import BoxMatch, find_all_anchors, find_anchor, text_from_boxes
from merchant.targeting import (
    ResolvedTarget,
    normalised_to_logical,
    resolve,
    resolve_all,
    screenshot_to_logical,
    summarise,
)


@dataclass
class FakeGeo:
    """Stands in for `screen.capture.ScreenShot` / `WindowShot`."""

    width: int = 1280            # downscaled screenshot
    height: int = 720
    physical_width: int = 2560   # real pixels
    physical_height: int = 1440
    dpi_scale: float = 2.0
    logical_left: int = 0
    logical_top: int = 0


def boxes_from(rows: list[tuple[str, int, int, int, int]]) -> list[WordBox]:
    return [WordBox(t, l, tp, w, h, confidence=90.0) for t, l, tp, w, h in rows]


SETTLEMENT_BOXES = boxes_from([
    ("Gross", 100, 200, 60, 18),
    ("amount", 165, 200, 70, 18),
    ("₹10,000", 400, 200, 80, 18),
    ("Razorpay", 100, 240, 85, 18),
    ("fees", 190, 240, 40, 18),
    ("₹200", 400, 240, 55, 18),
    ("Net", 100, 320, 35, 18),
    ("settlement", 140, 320, 95, 18),
    ("₹9,264", 400, 320, 75, 18),
])


# ── Coordinate conversion ─────────────────────────────────────────────────────


def test_screenshot_rect_converts_to_logical_pixels() -> None:
    geo = FakeGeo()
    # 1280-wide screenshot of a 2560px monitor at 200% DPI -> logical is 1280px.
    # So a screenshot x of 640 is physical 1280, logical 640.
    x, y, w, h = screenshot_to_logical(geo, 640, 360, 100, 20)
    assert x == pytest.approx(640.0)
    assert y == pytest.approx(360.0)
    assert w == pytest.approx(100.0)
    assert h == pytest.approx(20.0)


def test_conversion_accounts_for_dpi_and_monitor_origin() -> None:
    geo = FakeGeo(physical_width=2560, physical_height=1440, dpi_scale=1.0,
                  logical_left=1920, logical_top=0)
    x, _, w, _ = screenshot_to_logical(geo, 640, 0, 640, 10)
    # scale = 2560/1280 = 2, dpi 1 -> x = 1920 + 1280
    assert x == pytest.approx(3200.0)
    assert w == pytest.approx(1280.0)


def test_conversion_is_safe_when_geometry_is_degenerate() -> None:
    geo = FakeGeo(width=0, height=0)
    assert screenshot_to_logical(geo, 5, 6, 7, 8) == (5.0, 6.0, 7.0, 8.0)


def test_normalised_coordinates_convert() -> None:
    geo = FakeGeo(physical_width=2560, dpi_scale=2.0, logical_left=0)
    x, _ = normalised_to_logical(geo, 500, 0)
    assert x == pytest.approx(640.0)  # half of 1280 logical width


# ── OCR anchor search ─────────────────────────────────────────────────────────


def test_multi_word_anchor_is_found_as_one_box() -> None:
    match = find_anchor(SETTLEMENT_BOXES, "Gross amount")
    assert match is not None
    assert match.left == 100
    assert match.width == 135  # spans "Gross" through "amount"
    assert match.matched_text == "Gross amount"
    assert 0.0 < match.confidence <= 1.0


def test_anchor_search_is_case_and_space_insensitive() -> None:
    assert find_anchor(SETTLEMENT_BOXES, "gross  AMOUNT") is not None
    assert find_anchor(SETTLEMENT_BOXES, "Net Settlement") is not None


def test_anchor_not_present_returns_none() -> None:
    assert find_anchor(SETTLEMENT_BOXES, "Dispute evidence") is None
    assert find_anchor([], "Gross amount") is None
    assert find_anchor(SETTLEMENT_BOXES, "") is None


def test_anchor_does_not_match_across_two_lines() -> None:
    """'amount' on one row and 'Razorpay' on the next must not join up."""
    assert find_anchor(SETTLEMENT_BOXES, "amount Razorpay") is None


def test_find_all_anchors_omits_what_it_cannot_find() -> None:
    found = find_all_anchors(SETTLEMENT_BOXES, {
        "settlement.gross_amount": "Gross amount",
        "settlement.net_amount": "Net settlement",
        "settlement.utr": "UTR",
    })
    assert set(found) == {"settlement.gross_amount", "settlement.net_amount"}
    assert isinstance(found["settlement.gross_amount"], BoxMatch)


def test_text_from_boxes_reconstructs_lines() -> None:
    text = text_from_boxes(SETTLEMENT_BOXES)
    lines = text.splitlines()
    assert "Gross amount ₹10,000" in lines
    assert "Net settlement ₹9,264" in lines


# ── Tier selection ────────────────────────────────────────────────────────────


TARGET = HighlightTarget("settlement.gross_amount", "Gross amount", "Gross amount")


def test_dom_map_tier_wins_and_is_exact() -> None:
    r = resolve(TARGET, geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES,
                dom_map={"settlement.gross_amount": (500, 300, 120, 24)})
    assert r.found is True
    assert r.strategy is TargetStrategy.DOM_MAP
    assert (r.x, r.y, r.width, r.height) == (500.0, 300.0, 120.0, 24.0)
    assert r.confidence > 0.95


def test_falls_back_to_ocr_when_dom_map_lacks_the_target() -> None:
    r = resolve(TARGET, geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES,
                dom_map={"something.else": (0, 0, 5, 5)})
    assert r.found is True
    assert r.strategy is TargetStrategy.ANCHOR_TEXT
    assert r.x == pytest.approx(100.0)


def test_degenerate_dom_rect_is_ignored() -> None:
    """A zero-size rect is not a location; fall through rather than point at it."""
    r = resolve(TARGET, geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES,
                dom_map={"settlement.gross_amount": (10, 10, 0, 0)})
    assert r.strategy is TargetStrategy.ANCHOR_TEXT


@pytest.mark.parametrize("rect", [
    (500, -523, 89, 21),      # browser mis-estimated its chrome height
    (-900, 300, 89, 21),      # far off the left edge
    (500, 300, 0, 21),        # zero width
    (500, 300, 89, -5),       # negative height
    (99999, 300, 89, 21),     # absurd coordinate
    "not-a-rect",
    (1, 2, 3),                # wrong arity
])
def test_implausible_dom_rects_are_rejected_and_fall_through(rect) -> None:
    """A browser can publish a rect that is not a place on the desktop.

    Pointing there would put the cursor off-screen, so such a rect must be
    discarded in favour of a lower tier rather than trusted for being exact.
    """
    r = resolve(TARGET, geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES,
                dom_map={"settlement.gross_amount": rect})
    assert r.strategy is not TargetStrategy.DOM_MAP
    assert r.strategy is TargetStrategy.ANCHOR_TEXT  # fell through to OCR


def test_dom_rect_outside_the_captured_window_is_rejected() -> None:
    """The rect must overlap the window we actually captured."""
    geo = FakeGeo(physical_width=2560, physical_height=1440, dpi_scale=2.0,
                  logical_left=0, logical_top=0)  # logical bounds 1280x720
    r = resolve(TARGET, geo=geo, word_boxes=SETTLEMENT_BOXES,
                dom_map={"settlement.gross_amount": (5000, 4000, 89, 21)})
    assert r.strategy is TargetStrategy.ANCHOR_TEXT

    inside = resolve(TARGET, geo=geo, word_boxes=SETTLEMENT_BOXES,
                     dom_map={"settlement.gross_amount": (400, 300, 89, 21)})
    assert inside.strategy is TargetStrategy.DOM_MAP


def test_vlm_tier_is_used_only_as_a_last_resort_and_is_low_confidence() -> None:
    r = resolve(TARGET, geo=FakeGeo(), word_boxes=[], dom_map={},
                vlm_point=(500.0, 500.0))
    assert r.found is True
    assert r.strategy is TargetStrategy.VLM
    assert r.confidence < 0.5, "a model guess must not look authoritative"
    assert "double-check" in r.note


def test_unfindable_target_is_reported_not_guessed() -> None:
    r = resolve(TARGET, geo=FakeGeo(), word_boxes=[], dom_map={})
    assert r.found is False
    assert r.strategy is TargetStrategy.NONE
    assert (r.x, r.y, r.width, r.height) == (0.0, 0.0, 0.0, 0.0)
    assert "could not find" in r.note


def test_no_geometry_means_no_ocr_or_vlm_resolution() -> None:
    """Without a screenshot there is no coordinate space, so nothing resolves."""
    r = resolve(TARGET, geo=None, word_boxes=SETTLEMENT_BOXES, vlm_point=(1.0, 1.0))
    assert r.found is False


def test_resolve_all_preserves_order_and_marks_each_independently() -> None:
    targets = [
        HighlightTarget("settlement.gross_amount", "Gross amount", "Gross amount"),
        HighlightTarget("settlement.utr", "UTR", "UTR"),
        HighlightTarget("settlement.net_amount", "Net settlement", "Net settlement"),
    ]
    resolved = resolve_all(targets, geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES)
    assert [r.target.target_id for r in resolved] == [t.target_id for t in targets]
    assert [r.found for r in resolved] == [True, False, True]


def test_summarise_names_only_the_missing_targets() -> None:
    targets = [
        HighlightTarget("settlement.gross_amount", "Gross amount", "Gross amount"),
        HighlightTarget("settlement.utr", "UTR", "UTR"),
    ]
    resolved = resolve_all(targets, geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES)
    text = summarise(resolved)
    assert "UTR" in text
    assert "Gross amount" not in text

    all_found = resolve_all(targets[:1], geo=FakeGeo(), word_boxes=SETTLEMENT_BOXES)
    assert summarise(all_found) == ""


def test_resolved_center_is_the_middle_of_the_box() -> None:
    r = ResolvedTarget(target=TARGET, found=True, x=100.0, y=200.0,
                       width=60.0, height=20.0)
    assert r.center == (130.0, 210.0)


def test_server_side_targets_never_carry_coordinates() -> None:
    """The pipeline must emit semantic targets, not pixels."""
    import asyncio

    from merchant.audit import AuditLog
    from merchant.pipeline import MerchantPipeline, PipelineConfig, PipelineDeps
    from merchant.privacy import PrivacyState

    privacy = PrivacyState()
    privacy.grant_permission()
    pipe = MerchantPipeline(
        PipelineConfig(scenario_id="settlement_lower_than_gross"),
        PipelineDeps(privacy=privacy, audit=AuditLog()),
    )
    r = asyncio.run(pipe.ask("Mere payment ka settlement kam kyon aaya?"))

    assert r.highlight_targets
    for target in r.highlight_targets:
        assert target.rect is None, (
            f"{target.target_id} carries a pixel rect from the server side"
        )
        assert target.anchor_text, "every target needs an anchor to resolve by"
