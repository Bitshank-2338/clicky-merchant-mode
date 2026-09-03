"""
Highlight-target resolution.

The server side of Merchant Mode never emits pixel coordinates — it emits
semantic `HighlightTarget`s. This module is the client-side half that turns one
into an actual place on screen, using three tiers in order of trustworthiness:

  1. `dom_map`     — exact rects published by the mock dashboard. Screen pixels.
  2. `anchor_text` — OCR word-box search, converted screenshot → screen pixels.
  3. `vlm`         — vision-model coordinates, normalised 0-1000 (Clicky's
                     existing mechanism).

If every tier fails the result is `ResolvedTarget(found=False)` and the caller
must tell the merchant it cannot see the element. Pointing at a guess is worse
than admitting ignorance, because a confidently wrong arrow on a payments
screen can send someone to the wrong button.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from merchant.models import HighlightTarget, TargetStrategy, WordBox
from merchant.ocr_boxes import find_anchor


class ScreenGeometry(Protocol):
    """The subset of `screen.capture.ScreenShot` this module needs.

    Declared structurally so `targeting` never imports the capture module and
    stays testable without a display.
    """

    width: int             # downscaled screenshot width
    height: int            # downscaled screenshot height
    physical_width: int
    physical_height: int
    dpi_scale: float
    logical_left: int
    logical_top: int


# Nothing on a real desktop sits at these coordinates. A browser reports rects
# via `window.screenX/screenY` plus a chrome-height estimate, and that estimate
# goes wrong when the page is embedded, zoomed, or on a secondary monitor — it
# can hand back a negative Y. Pointing there would put the cursor off-screen,
# which is exactly the confidently-wrong behaviour this module exists to avoid.
MAX_PLAUSIBLE_COORD = 32_000
MAX_PLAUSIBLE_SIZE = 8_000


# A window may sit slightly off the top or left edge; more than this and the
# coordinate is not a place the merchant is looking.
OFFSCREEN_TOLERANCE = 64


def plausible_rect(rect: object, geo: Optional[ScreenGeometry] = None) -> bool:
    """True when a published rect could actually be a place on this desktop.

    When `geo` is supplied the rect must also overlap the captured window's
    logical bounds, which is the check that actually catches a browser's
    mis-estimated chrome height.
    """
    if not isinstance(rect, (tuple, list)) or len(rect) != 4:
        return False
    try:
        values = [float(v) for v in rect]
    except (TypeError, ValueError):
        return False
    x, y, w, h = values
    if w <= 0 or h <= 0:
        return False
    if w > MAX_PLAUSIBLE_SIZE or h > MAX_PLAUSIBLE_SIZE:
        return False
    if x < -OFFSCREEN_TOLERANCE or y < -OFFSCREEN_TOLERANCE:
        return False
    if x > MAX_PLAUSIBLE_COORD or y > MAX_PLAUSIBLE_COORD:
        return False

    if geo is not None:
        dpi = geo.dpi_scale or 1.0
        left, top = geo.logical_left, geo.logical_top
        right = left + geo.physical_width / dpi
        bottom = top + geo.physical_height / dpi
        # Reject a rect that does not overlap the window we actually captured.
        if x + w < left - OFFSCREEN_TOLERANCE or x > right + OFFSCREEN_TOLERANCE:
            return False
        if y + h < top - OFFSCREEN_TOLERANCE or y > bottom + OFFSCREEN_TOLERANCE:
            return False

    return True


@dataclass
class ResolvedTarget:
    """A highlight target that has (or has not) been located on screen."""

    target: HighlightTarget
    found: bool
    strategy: TargetStrategy = TargetStrategy.NONE
    # Logical screen pixels — the space `CursorOverlay` draws in.
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    confidence: float = 0.0
    note: str = ""

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)


def screenshot_to_logical(
    geo: ScreenGeometry, left: int, top: int, width: int, height: int
) -> tuple[float, float, float, float]:
    """Downscaled-screenshot rect → logical screen pixels.

    `screen/capture.py` downscales the JPEG to 1280px wide but keeps the true
    physical size on the ScreenShot, so the ratio between them is the scale
    factor. Dividing by `dpi_scale` moves physical → logical, and the monitor's
    logical origin handles multi-monitor layouts.
    """
    if geo.width <= 0 or geo.height <= 0:
        return (float(left), float(top), float(width), float(height))

    sx = geo.physical_width / float(geo.width)
    sy = geo.physical_height / float(geo.height)
    dpi = geo.dpi_scale or 1.0

    x = geo.logical_left + (left * sx) / dpi
    y = geo.logical_top + (top * sy) / dpi
    w = (width * sx) / dpi
    h = (height * sy) / dpi
    return (x, y, w, h)


def normalised_to_logical(
    geo: ScreenGeometry, nx: float, ny: float
) -> tuple[float, float]:
    """Normalised 0-1000 coordinates → logical screen pixels."""
    dpi = geo.dpi_scale or 1.0
    log_w = geo.physical_width / dpi
    log_h = geo.physical_height / dpi
    return (
        geo.logical_left + (nx / 1000.0) * log_w,
        geo.logical_top + (ny / 1000.0) * log_h,
    )


def resolve(
    target: HighlightTarget,
    *,
    geo: Optional[ScreenGeometry] = None,
    word_boxes: Optional[Sequence[WordBox]] = None,
    dom_map: Optional[dict[str, tuple[int, int, int, int]]] = None,
    vlm_point: Optional[tuple[float, float]] = None,
) -> ResolvedTarget:
    """Locate one target using the best tier that succeeds."""

    # Tier 1 — DOM map. Already in screen pixels; no conversion, no OCR error.
    if dom_map:
        rect = dom_map.get(target.target_id)
        if rect is not None and plausible_rect(rect, geo):
            x, y, w, h = rect
            return ResolvedTarget(
                target=target, found=True, strategy=TargetStrategy.DOM_MAP,
                x=float(x), y=float(y), width=float(w), height=float(h),
                confidence=0.99, note="located from the dashboard's own layout",
            )

    # Tier 2 — OCR anchor text.
    if word_boxes and geo is not None and target.anchor_text:
        match = find_anchor(word_boxes, target.anchor_text)
        if match is not None:
            x, y, w, h = screenshot_to_logical(
                geo, match.left, match.top, match.width, match.height
            )
            return ResolvedTarget(
                target=target, found=True, strategy=TargetStrategy.ANCHOR_TEXT,
                x=x, y=y, width=w, height=h,
                confidence=round(0.6 + 0.35 * match.confidence, 3),
                note=f"found the text '{match.matched_text}' on screen",
            )

    # Tier 3 — vision model point. Lowest trust: it is a guess, flagged as one.
    if vlm_point is not None and geo is not None:
        x, y = normalised_to_logical(geo, vlm_point[0], vlm_point[1])
        return ResolvedTarget(
            target=target, found=True, strategy=TargetStrategy.VLM,
            x=x - 40, y=y - 14, width=80, height=28,
            confidence=0.4, note="estimated from the screenshot — please double-check",
        )

    return ResolvedTarget(
        target=target, found=False, strategy=TargetStrategy.NONE,
        note=f"could not find '{target.anchor_text}' on this screen",
    )


def resolve_all(
    targets: Sequence[HighlightTarget],
    *,
    geo: Optional[ScreenGeometry] = None,
    word_boxes: Optional[Sequence[WordBox]] = None,
    dom_map: Optional[dict[str, tuple[int, int, int, int]]] = None,
) -> list[ResolvedTarget]:
    return [
        resolve(t, geo=geo, word_boxes=word_boxes, dom_map=dom_map)
        for t in targets
    ]


def summarise(resolved: Sequence[ResolvedTarget]) -> str:
    """One honest sentence about what could and could not be pointed at."""
    missing = [r.target.label for r in resolved if not r.found]
    if not missing:
        return ""
    if len(missing) == 1:
        return f"I could not find “{missing[0]}” on this screen."
    return "I could not find these on this screen: " + ", ".join(missing) + "."
