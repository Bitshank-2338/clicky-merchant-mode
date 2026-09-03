"""
Static checks on the mock dashboard's Clicky bridge.

The dashboard is plain JS with no build step and no test runner, so these read
it as text. They exist because two specific bugs were found by driving the real
page in a browser, and neither would be caught by the Python suite:

1. the bridge published rects with a negative screen Y (a mis-estimated browser
   chrome height), which would have made Clicky point off-screen;
2. the sidebar highlight was set independently of the rendered page, so it
   always said "Home" on first load and after a scenario switch.

Both are now fixed at the source. These assertions stop them coming back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_JS = REPO / "mockdashboard" / "app.js"
INDEX = REPO / "mockdashboard" / "index.html"


@pytest.fixture(scope="module")
def app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_bridge_functions_exist(app_js: str) -> None:
    assert "window.__clickyScreenMap" in app_js
    assert "window.__clickyPageId" in app_js


def test_published_rects_are_sanity_checked(app_js: str) -> None:
    """A rect that is not a place on the desktop must be omitted, not sent."""
    assert "isPlausibleRect" in app_js, "no rect validation in the bridge"

    body = app_js.split("function isPlausibleRect", 1)[1].split("\n}", 1)[0]
    assert "w <= 0" in body and "h <= 0" in body, "must reject zero-size rects"
    assert re.search(r"x\s*<\s*-\d+", body), "must reject far-negative x"
    assert re.search(r"y\s*<\s*-\d+", body), "must reject far-negative y"

    # And the check must actually gate the map, not just be defined.
    screen_map = app_js.split("window.__clickyScreenMap", 1)[1].split("\n};", 1)[0]
    assert "isPlausibleRect" in screen_map, "validation is defined but never applied"


def test_chrome_height_estimate_is_clamped_non_negative(app_js: str) -> None:
    """An embedded/zoomed browser can report a negative chrome height."""
    screen_map = app_js.split("window.__clickyScreenMap", 1)[1].split("\n};", 1)[0]
    combined = app_js.split("window.__clickyScreenMap", 1)[0][-400:] + screen_map
    assert "Math.max(0, window.outerHeight - window.innerHeight)" in combined, (
        "outerHeight - innerHeight must be clamped at zero"
    )


def test_nav_highlight_is_owned_by_render_page(app_js: str) -> None:
    """Exactly one place decides which nav item is active."""
    render_page = app_js.split("function renderPage", 1)[1]
    # Cut at the next top-level function definition.
    render_page = render_page.split("\nfunction ", 1)[0]
    assert 'classList.toggle("active"' in render_page, (
        "renderPage must set the active nav item itself"
    )

    # The old drift-prone code must be gone.
    assert "nav-item[data-page='home']" not in app_js, (
        "first load still hardcodes Home as the active nav item"
    )
    assert app_js.count('classList.remove("active")') == 0, (
        "nav highlight is still being cleared outside renderPage"
    )


def test_payment_link_form_cannot_submit_anywhere(app_js: str) -> None:
    assert "preventDefault" in app_js
    assert "api.razorpay.com" not in app_js


def test_bridge_posts_only_to_localhost(app_js: str) -> None:
    urls = re.findall(r"fetch\(\s*[\"']([^\"']+)[\"']", app_js)
    for url in urls:
        if url.startswith("http"):
            assert url.startswith("http://127.0.0.1:8756"), (
                f"dashboard reaches a non-local address: {url}"
            )


def test_every_dashboard_target_exists_in_the_seed() -> None:
    """Guard against pointing at an element that is not on the page."""
    import json

    seed = json.loads((REPO / "merchant" / "seed" / "dashboard_seed.json")
                      .read_text(encoding="utf-8"))
    anchors = {k for k in seed["ui_anchors"] if not k.startswith("_")}

    text = APP_JS.read_text(encoding="utf-8") + INDEX.read_text(encoding="utf-8")
    # Attributes appear both as plain HTML and inside JS template literals,
    # where the quotes are backslash-escaped.
    emitted = set(re.findall(r'data-clicky-target=\\?"([^"\\]+)', text))

    assert emitted, "no data-clicky-target attributes found at all"
    unknown = emitted - anchors
    assert not unknown, f"dashboard emits targets absent from the seed: {sorted(unknown)}"
