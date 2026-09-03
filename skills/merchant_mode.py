"""
Merchant Mode skill — routes merchant/dashboard questions to the read-only
Merchant Mode pipeline instead of Clicky's normal tutoring flow.

This is a purely *additive* skill. It plugs into Clicky's existing skill
contract (see `skills/__init__.py` and `skills/example_self_mode.py`): a
`SKILL` dict with a compiled-at-load-time `trigger` regex, tested before the
LLM runs. When a transcript does not match `SKILL["trigger"]`, this file is
never invoked and every one of Clicky's existing behaviours — tutoring,
self-mode, wake word, hotkey, all other skills — is completely untouched.

When the trigger *does* match, `handle_merchant` lazily creates (and caches
on the manager) a `merchant.pipeline.MerchantPipeline`, so Clicky's startup
cost is unchanged for users who never say a merchant phrase. It then takes a
best-effort, privacy-respecting look at the active window (masking screen
text before it ever leaves the function that produced it, and never writing
a screenshot to disk), asks the pipeline the question, optionally points
Clicky's cursor overlay at whatever was found on screen, and returns a plain
string for Clicky to speak/display. Any failure anywhere in this path is
caught and turned into a short apology — a bug in Merchant Mode must never
crash the rest of Clicky.
"""

from __future__ import annotations

import base64

from merchant.masking import mask_text
from merchant.models import ScreenContext, WordBox
from merchant.ocr_boxes import extract_word_boxes, tesseract_available, text_from_boxes
from merchant.pipeline import MerchantPipeline
from merchant.targeting import resolve_all


def _get_pipeline(manager: object) -> MerchantPipeline:
    """Lazily create and cache one MerchantPipeline per manager instance."""
    pipeline = getattr(manager, "_merchant_pipeline", None) if manager is not None else None
    if isinstance(pipeline, MerchantPipeline):
        return pipeline
    pipeline = MerchantPipeline()
    if manager is not None:
        try:
            setattr(manager, "_merchant_pipeline", pipeline)
        except Exception:
            pass
    return pipeline


def _build_screen_context(pipeline: MerchantPipeline) -> tuple[ScreenContext, object, list[WordBox]]:
    """Best-effort, privacy-respecting look at the active window.

    Returns an empty, uncaptured ScreenContext (never raising) when capture
    is not permitted, the capture module is unavailable, or anything about
    reading the screen fails. `merchant.ocr_boxes.tesseract_available()`
    being False is handled the same way: the pipeline still works, it just
    reasons about less.
    """
    if not pipeline.deps.privacy.capture_allowed:
        return ScreenContext(), None, []

    try:
        import screen.capture as capture_mod
    except Exception:
        return ScreenContext(), None, []

    capture_active = getattr(capture_mod, "capture_active_window", None)
    try:
        shot = capture_active() if callable(capture_active) else capture_mod.capture_primary()
    except Exception:
        shot = None
    if shot is None:
        return ScreenContext(), None, []

    word_boxes: list[WordBox] = []
    if tesseract_available():
        try:
            # Bytes live in this local variable only; nothing here is ever
            # written to disk.
            image_bytes = base64.b64decode(shot.base64_jpeg)
            word_boxes = extract_word_boxes(image_bytes)
        except Exception:
            word_boxes = []

    # Mask every word before it is attached to anything — screen text is
    # masked before it leaves the function that produced it.
    masked_boxes = [
        WordBox(
            text=mask_text(wb.text).text,
            left=wb.left,
            top=wb.top,
            width=wb.width,
            height=wb.height,
            confidence=wb.confidence,
        )
        for wb in word_boxes
    ]
    combined = mask_text(text_from_boxes(word_boxes))
    pipeline.deps.privacy.note_capture(combined.total)

    window_title = str(getattr(shot, "window_title", "") or "")
    if window_title:
        window_title = mask_text(window_title).text

    ctx = ScreenContext(
        ocr_text=combined.text,
        word_boxes=masked_boxes,
        window_title=window_title,
        url_hint="",
        dom_map={},
        screenshot_width=int(getattr(shot, "width", 0) or 0),
        screenshot_height=int(getattr(shot, "height", 0) or 0),
        captured=True,
        masked_field_count=combined.total,
    )
    return ctx, shot, masked_boxes


async def handle_merchant(manager: object, transcript: str) -> str:
    try:
        pipeline = _get_pipeline(manager)
        screen, geo, word_boxes = _build_screen_context(pipeline)

        response = await pipeline.ask(transcript, screen)

        overlay = getattr(manager, "overlay", None) if manager is not None else None
        if overlay is not None and response.highlight_targets:
            resolved = resolve_all(
                response.highlight_targets, geo=geo, word_boxes=word_boxes, dom_map={},
            )
            for item in resolved:
                if not item.found:
                    continue
                cx, cy = item.center
                try:
                    overlay.point_at(cx, cy, item.target.label)
                except Exception:
                    pass

        answer = response.answer or ""
        if response.steps:
            answer = f"{answer} Next: {response.steps[0].title}".strip()
        return answer
    except Exception:
        return (
            "Sorry, Merchant Mode ran into a problem answering that. "
            "Please try asking again."
        )


SKILL = {
    "name": "Merchant Mode",
    "trigger": (
        r"(merchant\s*mode|settlement|payment\s*links?|refunds?|"
        r"failed\s*payments?|payment\s*fail(?:ed|ure)?|"
        r"dukaan|dukan|paisa\s*kam|paise\s*kam|kam\s*kyo(?:n|un)?\s*aaya|"
        r"kam\s*(?:kyo(?:n|un)?\s*)?aaya|\bfees?\b|commission|"
        r"सेटलमेंट|रिफ़?ंड|पेमेंट\s*लिंक|फेल(?:ड)?\s*पेमेंट|दुकान|"
        r"पैसा\s*कम|पैसे\s*कम|कम\s*(?:आया|मिला|क्यों|क्यूँ)|"
        # Guide-Me progression. Deliberately NOT bare "next"/"continue":
        # `tutor.NEXT_RE` owns those for Clicky's own lessons and is checked
        # before skills are, so claiming them here would shadow existing
        # behaviour. These longer merchant-flavoured phrases are free.
        r"^\s*(?:next\s*step|agla\s*step|aage|agla|ho\s*gaya|kar\s*liya|"
        r"आगे|अगला)\s*[.!?]*$)"
    ),
    "description": (
        "Answers merchant/dashboard questions (settlements, refunds, "
        "payment links, failed payments, fees) using the read-only "
        "Merchant Mode pipeline instead of general tutoring."
    ),
    "handler": handle_merchant,
}
