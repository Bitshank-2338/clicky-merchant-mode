"""
"Where is X?" — finding an arbitrary thing the merchant names.

Every other Merchant Mode intent explains something. This one *points*, which
is the whole reason a merchant would prefer Clicky to a help article: they are
looking at a screen full of controls and cannot find one.

Until this existed, Merchant Mode could only point at the ~30 anchors baked
into the seed. Asked "where is the issue button", it either fell through to the
general assistant or — worse — matched `refund_tutorial` and delivered a
lecture about refunds. Both are the failure the product is meant to avoid.

Here the named phrase becomes the anchor directly, so `merchant.targeting`
resolves it against whatever is actually on screen. If OCR cannot find it,
Clicky says so rather than pointing somewhere plausible.
"""

from __future__ import annotations

import re
from typing import Optional

# Words that mean "a thing on the screen". Their presence is what separates
# "where is the refund button" (point at it) from "how do I refund" (teach).
UI_NOUNS = (
    "button", "tab", "menu", "option", "field", "box", "icon", "link",
    "column", "filter", "dropdown", "drop down", "toggle", "checkbox",
    "section", "row", "card", "heading", "label", "bar", "panel", "page",
    "batan", "buton",                        # common ASR renderings
    "बटन", "टैब", "मेन्यू", "विकल्प",
)

_UI_NOUN_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in UI_NOUNS) + r")\b", re.IGNORECASE
)

# "Where is it?" phrasing, in all three languages.
_WHERE_RE = re.compile(
    r"\bwhere\s+(?:is|are|can i find|do i find)\b"
    r"|\bkahan\s+(?:hai|hain|par|pe|milega|milta)\b"
    r"|\bkidhar\s+(?:hai|hain)\b"
    r"|कहाँ\s*(?:है|हैं)|कहां\s*(?:है|हैं)",
    re.IGNORECASE,
)

# "Show me ..." phrasing. On its own this is not enough — "failed payments
# dikhao" is a data request, not a locate request — so it must be paired with
# a UI noun or a "where" phrase.
_SHOW_RE = re.compile(
    r"\b(?:show|point|find|locate|highlight)\b"
    r"|\bdikha(?:o|iye|na|do)\b|\bbata(?:o|iye)\b"
    r"|दिखा(?:ओ|इए)|बता(?:ओ|इए)",
    re.IGNORECASE,
)


def is_locate_request(text: str) -> bool:
    """True when the merchant is asking to be shown *where* something is.

    Deliberately conservative: it needs an explicit UI noun ("button", "tab"),
    or "where is"-style phrasing. "Kal ke failed payments dikhao" contains
    "dikhao" but names no control, so it stays a data request.
    """
    if not text or not text.strip():
        return False
    has_where = bool(_WHERE_RE.search(text))
    has_ui_noun = bool(_UI_NOUN_RE.search(text))
    has_show = bool(_SHOW_RE.search(text))
    return has_where or (has_ui_noun and has_show)


# Filler that surrounds the thing being asked about.
_STRIP_PREFIX = re.compile(
    # "I didn't see the issue button" -> "issue button". Each piece is optional
    # because merchants phrase this a dozen ways.
    r"^(?:(?:i|mujhe)\s+)?"
    r"(?:(?:can'?t|cannot|could\s*not|didn'?t|dont|don'?t|not)\s+)?"
    r"(?:(?:see|find|saw|dekha|mila|milta)\s+)?"
    r"(?:(?:the|a|an|my|is|are|that|this|it)\s+)*",
    re.IGNORECASE,
)
_STRIP_SUFFIX = re.compile(
    r"\s*(?:can\s+you\s+)?(?:please\s+)?"
    r"(?:show\s+me\s+)?(?:where\s+(?:it\s+)?is)?\s*[?.!]*$",
    re.IGNORECASE,
)
_NOISE_WORDS = {
    "please", "clicky", "hey", "ok", "okay", "just", "me", "mujhe", "mujhko",
    "yeh", "ye", "wo", "woh", "ka", "ki", "ke", "hai", "hain", "kahan",
    "kidhar", "par", "pe", "ko",
    # Pronouns. "Where is it?" names nothing findable — searching the screen
    # for the word "it" would point somewhere meaningless, so this must fall
    # through to "tell me what you're looking for" instead.
    "it", "its", "this", "that", "these", "those", "they", "them", "one",
    "thing", "here", "there",
}

# Patterns that carry the named thing in group 1, best first.
_CAPTURE = (
    # "show me where the issue button is" — must not capture the whole clause.
    re.compile(r"\b(?:show|tell)\s+me\s+where\s+(?:the\s+|a\s+|my\s+)?(.+?)"
               r"\s+(?:is|are)\s*[?.!]*$", re.I),
    re.compile(r"\bwhere\s+(?:is|are)\s+(?:the\s+|a\s+|my\s+)?(.+?)\s*[?.!]*$", re.I),
    re.compile(r"\bwhere\s+(?:can|do)\s+i\s+find\s+(?:the\s+)?(.+?)\s*[?.!]*$", re.I),
    re.compile(r"\b(?:show|point\s+to|point\s+at|find|locate|highlight)\s+"
               r"(?:me\s+)?(?:the\s+|a\s+|my\s+)?(.+?)"
               r"(?:\s+(?:on|in)\s+(?:the\s+)?(?:screen|page|dashboard))?\s*[?.!]*$", re.I),
    re.compile(r"(.+?)\s+(?:kahan|kidhar)\s+(?:hai|hain|par|pe|milega|milta)", re.I),
    re.compile(r"(.+?)\s+(?:कहाँ|कहां)\s*(?:है|हैं)", re.I),
    re.compile(r"(?:mujhe\s+)?(.+?)\s+dikha(?:o|iye|na|do)\b", re.I),
    re.compile(r"(.+?)\s+दिखा(?:ओ|इए)", re.I),
)


def extract_target(text: str) -> Optional[str]:
    """Pull the thing being asked about out of the sentence.

    "I didn't see the issue button, can you show me where it is?"
        -> "issue button"

    Returns `None` when nothing usable is left, which the caller must treat as
    "I don't know what you mean" rather than pointing at a guess.
    """
    if not text:
        return None

    # "…the issue button, can you show me where it is?" — the tail is filler
    # wrapped around the real question, so cut it before matching.
    cleaned = re.sub(r",?\s*(?:can\s+you\s+)?(?:please\s+)?show\s+me\s+where\s+"
                     r"(?:it|they)\s+(?:is|are)\s*[?.!]*$", "", text, flags=re.I)

    candidate: Optional[str] = None
    for pattern in _CAPTURE:
        m = pattern.search(cleaned)
        if m:
            candidate = m.group(1)
            break

    if candidate is None:
        # No capture matched, but a UI noun may still name the thing —
        # "issue button" inside a longer sentence.
        m = re.search(r"([A-Za-z0-9₹][\w₹'’\-]*(?:\s+[\w₹'’\-]+){0,3}\s+"
                      + _UI_NOUN_RE.pattern[2:-2] + r")", cleaned, re.IGNORECASE)
        if m:
            candidate = m.group(1)

    if candidate is None:
        return None

    candidate = _STRIP_SUFFIX.sub("", candidate)
    candidate = _STRIP_PREFIX.sub("", candidate).strip(" ,.?!\"'")

    words = [w for w in candidate.split() if w.lower() not in _NOISE_WORDS]
    # A locate query longer than this is a sentence, not a label.
    if not words or len(words) > 6:
        return None

    result = " ".join(words).strip()
    return result or None


def search_terms(target: str) -> list[str]:
    """Anchor candidates to try, most specific first.

    A merchant says "the issue button" but the screen says "Issue". Dropping
    the UI noun is usually what finds it, so try the full phrase first and the
    phrase without its trailing noun second.
    """
    if not target:
        return []
    terms = [target]
    trailing_noun = re.compile(
        r"\s+(?:" + "|".join(re.escape(n) for n in UI_NOUNS) + r")\s*$",
        re.IGNORECASE,
    )
    without_noun = trailing_noun.sub("", target).strip(" ,.-")
    if without_noun and without_noun.lower() != target.lower():
        terms.append(without_noun)
    return terms
