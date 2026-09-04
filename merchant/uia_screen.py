"""
Reading the foreground window through Windows UI Automation.

Tesseract is optional, and on a machine without it Merchant Mode would be blind
on the real Razorpay dashboard — no OCR text to read amounts from, no word
boxes to locate rows with. But a browser already publishes everything we need
through its accessibility tree: the rendered text *and* the exact screen
rectangle of every element.

So this module is the non-OCR path to the same two things:

* `harvest()` — visible text plus `{label: rect}` for the foreground window.
* `make_lookup()` — an anchor-text → rect callable for `merchant.targeting`.

It is Windows-only and entirely optional. Every function degrades to "nothing
found" rather than raising, so the pipeline behaves exactly as it does on a
machine with no accessibility support at all.

Privacy note: this reads the *foreground window only*, exactly like the
screenshot path, and the text it returns is masked by the caller before it goes
anywhere — see `merchant.masking`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# Walking a large accessibility tree is not free, and a merchant dashboard can
# be thousands of nodes. These caps keep a capture well under a second.
MAX_NODES = 4000
MAX_DEPTH = 28
TIME_BUDGET_SECONDS = 2.5

# Controls whose text is chrome rather than content.
_SKIP_TYPES = {"TitleBarControl", "ScrollBarControl", "MenuBarControl"}


def uia_available() -> bool:
    try:
        import uiautomation  # noqa: F401
    except Exception:
        return False
    return True


@dataclass
class UiaHarvest:
    """What the accessibility tree could tell us about the current window."""

    text: str = ""
    rects: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    window_title: str = ""
    node_count: int = 0
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.text or self.rects)


def _rect_of(control) -> Optional[tuple[int, int, int, int]]:
    """Element bounds as (x, y, w, h) in logical screen pixels, or None."""
    try:
        r = control.BoundingRectangle
    except Exception:
        return None
    try:
        left, top, right, bottom = int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:
        return None
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    return (left, top, w, h)


def harvest(max_nodes: int = MAX_NODES,
            time_budget: float = TIME_BUDGET_SECONDS) -> UiaHarvest:
    """Read text and element rects from the foreground window.

    Returns an empty harvest on any failure — a missing accessibility tree is
    an ordinary condition, not an error.
    """
    out = UiaHarvest()
    if not uia_available():
        return out

    try:
        import uiautomation as auto
    except Exception:
        return out

    deadline = time.monotonic() + time_budget

    try:
        window = auto.GetForegroundControl()
        if window is None:
            return out
        try:
            out.window_title = str(window.Name or "")
        except Exception:
            out.window_title = ""

        lines: list[str] = []
        seen_text: set[str] = set()
        stack: list[tuple[object, int]] = [(window, 0)]

        while stack:
            if time.monotonic() > deadline:
                out.truncated = True
                break
            if out.node_count >= max_nodes:
                out.truncated = True
                break

            control, depth = stack.pop()
            out.node_count += 1

            try:
                control_type = control.ControlTypeName
            except Exception:
                control_type = ""
            if control_type in _SKIP_TYPES:
                continue

            name = ""
            try:
                name = (control.Name or "").strip()
            except Exception:
                pass

            if name and len(name) <= 200:
                if name not in seen_text:
                    seen_text.add(name)
                    lines.append(name)
                # Keep the first rect for a given label: on a dashboard the
                # first occurrence is the row itself, later ones tend to be
                # summaries or repeats.
                if name not in out.rects:
                    rect = _rect_of(control)
                    if rect is not None:
                        out.rects[name] = rect

            if depth < MAX_DEPTH:
                try:
                    children = control.GetChildren()
                except Exception:
                    children = []
                # Reversed so the natural reading order survives the stack.
                for child in reversed(children):
                    stack.append((child, depth + 1))

        out.text = "\n".join(lines)
    except Exception:
        return UiaHarvest()

    return out


# ── Anchor lookup for merchant.targeting ──────────────────────────────────────


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def make_lookup(harvested: Optional[UiaHarvest] = None
                ) -> Optional[Callable[[str], Optional[tuple]]]:
    """Build an `anchor_text -> rect` callable over a harvest.

    Returns `None` when there is nothing to look up, so callers can pass the
    result straight to `merchant.targeting.resolve` without a branch.
    """
    data = harvested if harvested is not None else harvest()
    if not data.rects:
        return None

    index = {_norm(label): rect for label, rect in data.rects.items()}

    def lookup(anchor: str) -> Optional[tuple]:
        key = _norm(anchor)
        if not key:
            return None
        hit = index.get(key)
        if hit is not None:
            return hit
        # A dashboard often renders "Gross amount" inside a longer label such
        # as "Gross amount ₹47,320". Prefer the shortest containing label, as
        # that is the tightest box around the thing we actually want.
        best: Optional[tuple[int, tuple]] = None
        for label_key, rect in index.items():
            if key in label_key:
                score = len(label_key)
                if best is None or score < best[0]:
                    best = (score, rect)
        return best[1] if best else None

    return lookup
