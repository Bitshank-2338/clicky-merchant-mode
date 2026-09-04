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

import asyncio
import base64
import re

from merchant.masking import mask_text
from merchant.models import ScreenContext, WordBox
from merchant.ocr_boxes import extract_word_boxes, ocr_backend, text_from_boxes
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
    reading the screen fails. No OCR engine being installed is handled the
    same way: the pipeline still works, it just reasons about less.
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
    if ocr_backend():
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


# How long the cursor rests on one element before moving to the next. The
# overlay's flight animation alone is ~1.8s.
POINT_DWELL_SECONDS = 2.6


async def _point_at_each(manager: object, resolved: list) -> None:
    """Walk the cursor across the located elements, one at a time.

    Emits through the manager's Qt signals rather than touching the overlay
    object directly. Two reasons, both of which bit us:

    * `main.py` wires the overlay to `manager.sig_point_at` but never assigns
      `manager.overlay`, so the direct route silently did nothing in full
      Clicky — the answer was spoken but the cursor never moved.
    * This coroutine runs on the manager's asyncio loop on a worker thread.
      Calling into a QWidget from there is a cross-thread GUI call; a signal
      marshals it onto the GUI thread properly.

    Falls back to a direct `manager.overlay` reference for hosts that do expose
    one (the standalone `run_merchant_mode.py` launcher does).
    """
    if not resolved:
        return

    point = getattr(manager, "sig_point_at", None) if manager is not None else None
    circle = getattr(manager, "sig_circle", None) if manager is not None else None
    overlay = getattr(manager, "overlay", None) if manager is not None else None

    for index, item in enumerate(resolved):
        cx, cy = item.center
        radius = max(item.width, item.height, 24.0) / 2.0 + 6.0
        try:
            if point is not None and hasattr(point, "emit"):
                point.emit(float(cx), float(cy), str(item.target.label))
                if circle is not None and hasattr(circle, "emit"):
                    circle.emit(float(cx), float(cy), float(radius))
            elif overlay is not None:
                overlay.point_at(cx, cy, item.target.label)
                overlay.add_circle(cx, cy, radius, ttl=POINT_DWELL_SECONDS * 3)
        except Exception:
            pass

        if index < len(resolved) - 1:
            await asyncio.sleep(POINT_DWELL_SECONDS)


# Spoken consent. Merchant Mode refuses to read the screen until permission is
# given, and in full Clicky there is no panel button to give it — so the
# merchant grants (and revokes) it out loud. Kept as an explicit phrase rather
# than an implicit "asking implies consent", because the whole point is that
# the merchant decides.
_GRANT = re.compile(
    r"\b(allow|enable|start|grant)\b.{0,20}\b(screen|reading|dekh|padh)\b"
    r"|\bscreen\s*(padho|padhna|dekho|dekhna|read karo)\b"
    r"|\b(haan|haa|yes|ok|okay|theek hai)\b.{0,15}\b(padh|dekh|read|allow)\b"
    r"|स्क्रीन.{0,15}(पढ़|देख)",
    re.IGNORECASE,
)

_REVOKE = re.compile(
    r"\b(stop|band|bandh|disable)\b.{0,20}\b(monitor|screen|reading|dekh|padh)\b"
    r"|\bstop monitoring\b|\bscreen band\b"
    r"|स्क्रीन.{0,15}बंद",
    re.IGNORECASE,
)


def _consent_reply(granted: bool, transcript: str) -> str:
    hinglish = bool(re.search(r"[ऀ-ॿ]|padh|dekh|haan|band", transcript, re.I))
    if granted:
        return ("Theek hai, ab main sirf wahi window padhungi jo aap dekh rahe hain. "
                "Kuch bhi save nahi hota. Ab poochiye."
                if hinglish else
                "Done — I will read only the window you are looking at, and nothing "
                "is saved. Ask me anything now.")
    return ("Screen padhna band kar diya. Ab main kuch nahi dekh rahi."
            if hinglish else
            "Screen reading stopped. I am not looking at anything now.")


async def handle_merchant(manager: object, transcript: str) -> str:
    try:
        pipeline = _get_pipeline(manager)

        # Consent first — before any capture happens.
        if _REVOKE.search(transcript or ""):
            pipeline.stop_monitoring()
            return _consent_reply(False, transcript)
        if _GRANT.search(transcript or ""):
            pipeline.deps.privacy.grant_permission()
            return _consent_reply(True, transcript)

        screen, geo, word_boxes = _build_screen_context(pipeline)

        response = await pipeline.ask(transcript, screen)

        if response.highlight_targets:
            uia_lookup = None
            try:
                from merchant.uia_screen import make_lookup

                uia_lookup = make_lookup()
            except Exception:
                uia_lookup = None

            resolved = resolve_all(
                response.highlight_targets, geo=geo, word_boxes=word_boxes,
                dom_map={}, uia_lookup=uia_lookup,
            )
            await _point_at_each(manager, [r for r in resolved if r.found])

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
        r"आगे|अगला)\s*[.!?]*$|"
        # Spoken consent to start/stop screen reading. Without these in the
        # trigger the consent handler below could never be reached.
        r"(?:allow|enable|grant|start)\s*(?:screen|reading)|screen\s*(?:padho|dekho|reading)|"
        r"stop\s*monitoring|screen\s*band|स्क्रीन\s*(?:पढ़|देख|बंद))"
    ),
    "description": (
        "Answers merchant/dashboard questions (settlements, refunds, "
        "payment links, failed payments, fees) using the read-only "
        "Merchant Mode pipeline instead of general tutoring."
    ),
    "handler": handle_merchant,
}
