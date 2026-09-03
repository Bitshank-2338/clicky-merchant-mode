"""
OCR with per-word bounding boxes.

Clicky's existing `tutor_features/ocr.py` returns text only, which is enough to
*read* a screen but not to *point* at part of it. Merchant Mode needs boxes, so
this module wraps `pytesseract.image_to_data`.

Tesseract is optional. When it is missing every function degrades to "no boxes"
and the pipeline falls back to a lower targeting tier — it never raises.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from merchant.models import WordBox

_MIN_CONFIDENCE = 35.0


def tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_word_boxes(image_bytes: bytes) -> list[WordBox]:
    """Return per-word boxes in the coordinate space of `image_bytes`.

    Returns `[]` if Tesseract is unavailable or the image cannot be read.
    """
    if not image_bytes:
        return []
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return []

    try:
        img = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(
            img, output_type=pytesseract.Output.DICT
        )
    except Exception:
        return []

    boxes: list[WordBox] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < _MIN_CONFIDENCE:
            continue
        boxes.append(WordBox(
            text=text,
            left=int(data["left"][i]),
            top=int(data["top"][i]),
            width=int(data["width"][i]),
            height=int(data["height"][i]),
            confidence=conf,
        ))
    return boxes


def text_from_boxes(boxes: Sequence[WordBox]) -> str:
    """Reassemble readable text from boxes, grouping words into lines."""
    if not boxes:
        return ""
    ordered = sorted(boxes, key=lambda b: (b.top, b.left))
    lines: list[list[WordBox]] = []
    for b in ordered:
        placed = False
        for line in lines:
            # Same line if vertical centres are within half a word-height.
            ref = line[0]
            if abs((b.top + b.height / 2) - (ref.top + ref.height / 2)) <= ref.height * 0.6:
                line.append(b)
                placed = True
                break
        if not placed:
            lines.append([b])
    return "\n".join(
        " ".join(w.text for w in sorted(line, key=lambda w: w.left))
        for line in lines
    )


# ── Anchor search ─────────────────────────────────────────────────────────────


@dataclass
class BoxMatch:
    """A located phrase: its box in screenshot space plus how sure we are."""

    left: int
    top: int
    width: int
    height: int
    confidence: float
    matched_text: str

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.width / 2.0, self.top + self.height / 2.0)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9₹]+", "", s.lower())


def find_anchor(boxes: Sequence[WordBox], anchor: str) -> Optional[BoxMatch]:
    """Locate `anchor` (which may be several words) among OCR word boxes.

    Matches a contiguous run of words whose concatenation equals the anchor's
    normalised form. Falls back to the single best word match for one-word
    anchors. Returns `None` when nothing matches — the caller must then not
    point at anything.
    """
    if not boxes or not anchor.strip():
        return None

    target = _norm(anchor)
    if not target:
        return None

    ordered = sorted(boxes, key=lambda b: (b.top, b.left))
    words = [w for w in anchor.split() if w]
    span = len(words)

    best: Optional[BoxMatch] = None

    # Try contiguous windows of the anchor's word count, then a little wider to
    # absorb OCR splitting a word in two.
    for width in range(span, span + 2):
        for i in range(len(ordered) - width + 1):
            window = ordered[i:i + width]
            # Reject windows that straddle lines.
            ref = window[0]
            if any(abs(w.top - ref.top) > ref.height * 1.2 for w in window):
                continue
            joined = _norm("".join(w.text for w in window))
            if joined != target:
                continue
            left = min(w.left for w in window)
            top = min(w.top for w in window)
            right = max(w.right for w in window)
            bottom = max(w.bottom for w in window)
            conf = sum(w.confidence for w in window) / len(window) / 100.0
            candidate = BoxMatch(left, top, right - left, bottom - top,
                                 round(conf, 3), " ".join(w.text for w in window))
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        if best is not None:
            return best

    # Single-token fallback: prefix match on a distinctive word.
    if span == 1 and len(target) >= 4:
        for w in ordered:
            if _norm(w.text).startswith(target):
                return BoxMatch(w.left, w.top, w.width, w.height,
                                round(w.confidence / 100.0 * 0.8, 3), w.text)
    return None


def find_all_anchors(
    boxes: Sequence[WordBox], anchors: dict[str, str]
) -> dict[str, BoxMatch]:
    """Resolve `{target_id: anchor_text}` to `{target_id: BoxMatch}`.

    Target ids that could not be located are simply absent from the result.
    """
    out: dict[str, BoxMatch] = {}
    for target_id, anchor in anchors.items():
        match = find_anchor(boxes, anchor)
        if match is not None:
            out[target_id] = match
    return out
