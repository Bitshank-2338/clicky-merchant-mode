"""
Multi-monitor screenshot helper.

The tricky part is keeping THREE coordinate systems straight:

  1. PHYSICAL  — what mss.grab() returns. Real GPU pixels. e.g. 2560x1440.
  2. LOGICAL   — what the OS / Qt cursor uses after DPI scaling. e.g. 1707x960
                 on a 150%-DPI 2560x1440 display.
  3. DOWNSCALED — what we send to the LLM (1280-wide JPEG to keep tokens low).

The overlay plots in LOGICAL coordinates. The element-detector model sees the
downscaled image. So `detect_element` must return coords in LOGICAL space, with
the monitor's logical-origin offset applied for multi-monitor setups.

ScreenShot now carries every number needed to convert between them.
"""

import base64
import ctypes
import ctypes.wintypes
import io
from dataclasses import dataclass
from typing import List, Optional

import mss
import mss.tools
from PIL import Image


@dataclass
class ScreenShot:
    index: int

    # Downscaled image actually sent to the LLM
    width: int            # downscaled width (pixels in JPEG)
    height: int           # downscaled height
    base64_jpeg: str

    # Real (physical) monitor size and origin in mss virtual-screen coords
    physical_width: int
    physical_height: int
    physical_left: int    # mss-reported origin (physical px)
    physical_top: int

    # DPI scale (physical / logical). 1.0 on normal displays, 1.5 on 150% DPI.
    dpi_scale: float

    # Convenience: where this monitor's top-left sits in LOGICAL screen space
    logical_left: int
    logical_top: int


def _query_dpi_scale() -> float:
    """Best-effort DPI scale for the primary monitor.
    Returns 1.0 if anything goes wrong."""
    try:
        # GetDpiForSystem returns DPI as integer (96 = 100%, 144 = 150%)
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        gdfs = getattr(u, "GetDpiForSystem", None)
        if gdfs:
            return max(1.0, gdfs() / 96.0)
        # Fallback: ratio of GetSystemMetrics(physical) vs (logical)
        return 1.0
    except Exception:
        return 1.0


def capture_all_screens(max_width: int = 1280) -> List[ScreenShot]:
    """Capture all monitors. Each ScreenShot carries everything needed
    to convert detection coords back into logical screen space."""
    dpi = _query_dpi_scale()
    results = []
    with mss.mss() as sct:
        # mss monitor index 0 is the combined virtual screen; 1+ are real monitors
        for i, monitor in enumerate(sct.monitors[1:], start=1):
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            phys_w, phys_h = img.width, img.height
            phys_left = int(monitor.get("left", 0))
            phys_top  = int(monitor.get("top",  0))

            # Downscale only the JPEG we send to the LLM — keep physical numbers intact
            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize(
                    (max_width, int(img.height * ratio)),
                    Image.Resampling.LANCZOS,
                )

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

            results.append(ScreenShot(
                index=i,
                width=img.width,
                height=img.height,
                base64_jpeg=encoded,
                physical_width=phys_w,
                physical_height=phys_h,
                physical_left=phys_left,
                physical_top=phys_top,
                dpi_scale=dpi,
                logical_left=int(round(phys_left / dpi)),
                logical_top=int(round(phys_top  / dpi)),
            ))

    return results


def capture_primary() -> ScreenShot:
    """Capture only the primary monitor."""
    screens = capture_all_screens()
    return screens[0] if screens else None


def screen_count() -> int:
    with mss.mss() as sct:
        return len(sct.monitors) - 1  # subtract virtual combined monitor


# ─────────────────────────────────────────────────────────────────────────────
# Active-window capture (added for Merchant Mode)
#
# Clicky's original capture grabs whole monitors. Merchant Mode promises the
# user that only the window they are actually looking at is read — never the
# rest of the desktop, never a second monitor. That promise needs its own
# capture path, so this is additive: nothing above changed.
#
# WindowShot deliberately mirrors ScreenShot's geometry fields so the same
# coordinate conversions (merchant/targeting.py) work for both.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WindowShot:
    """A screenshot of one window, with the geometry needed to map back."""

    title: str

    # Downscaled image (what OCR and any model sees)
    width: int
    height: int
    base64_jpeg: str
    jpeg_bytes: bytes

    # The window's real rectangle, in physical pixels
    physical_width: int
    physical_height: int
    physical_left: int
    physical_top: int

    dpi_scale: float

    # The window's top-left in LOGICAL screen space — what the overlay draws in
    logical_left: int
    logical_top: int

    captured: bool = True


def active_window_rect() -> Optional[dict]:
    """Bounds and title of the foreground window, in physical pixels.

    Uses DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS) where available so
    the invisible resize border Windows 10/11 report from GetWindowRect does not
    offset every coordinate by ~7px. Returns None off Windows or on failure.
    """
    try:
        u = ctypes.windll.user32
    except (AttributeError, OSError):
        return None  # not Windows

    try:
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        rect = _RECT()
        got = False
        try:
            dwm = ctypes.windll.dwmapi
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            hr = dwm.DwmGetWindowAttribute(
                ctypes.wintypes.HWND(hwnd),
                ctypes.wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            got = (hr == 0)
        except Exception:
            got = False

        if not got:
            if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None

        length = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, buf, length + 1)

        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return None

        return {
            "left": int(rect.left), "top": int(rect.top),
            "width": width, "height": height,
            "title": buf.value or "",
        }
    except Exception:
        return None


def capture_active_window(max_width: int = 1280) -> Optional[WindowShot]:
    """Capture ONLY the foreground window.

    Returns None when there is no usable foreground window (or off Windows), so
    callers must handle absence — Merchant Mode treats that as "I cannot see
    your screen" rather than silently falling back to a full-desktop grab,
    which would break the active-window-only privacy promise.

    The JPEG bytes are returned in-memory and are never written to disk.
    """
    box = active_window_rect()
    if box is None:
        return None

    dpi = _query_dpi_scale()

    try:
        with mss.mss() as sct:
            raw = sct.grab({
                "left": box["left"], "top": box["top"],
                "width": box["width"], "height": box["height"],
            })
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    except Exception:
        return None

    phys_w, phys_h = img.width, img.height
    if phys_w == 0 or phys_h == 0:
        return None

    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, max(1, int(img.height * ratio))),
                         Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    jpeg = buf.getvalue()

    return WindowShot(
        title=box["title"],
        width=img.width,
        height=img.height,
        base64_jpeg=base64.b64encode(jpeg).decode("utf-8"),
        jpeg_bytes=jpeg,
        physical_width=phys_w,
        physical_height=phys_h,
        physical_left=box["left"],
        physical_top=box["top"],
        dpi_scale=dpi,
        logical_left=int(round(box["left"] / dpi)),
        logical_top=int(round(box["top"] / dpi)),
    )
