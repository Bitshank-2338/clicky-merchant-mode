"""
Launch Merchant Mode for a live demo or a screen recording.

Starts only what a demo needs — Clicky's `CursorOverlay` plus the
`MerchantPanel` — and skips the audio, wake-word and hotkey stacks that
`main.py` brings up. That keeps startup to a second or two and means no
microphone permission, no Whisper model download, and nothing to go wrong on
stage.

    python run_merchant_mode.py

Then type a question into the panel. The buddy cursor flies to each element it
found, one at a time, exactly as it does inside full Clicky.

Use `python main.py` for the complete Clicky experience including voice.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

BANNER = r"""
  Clicky Merchant Mode — demo launcher
  ------------------------------------
"""


def _report_environment() -> None:
    """Print what the demo can and cannot do on this machine, before it starts.

    Better to know the cursor will not point at anything *before* the camera
    is rolling.
    """
    from merchant.adapters import get_adapter
    from merchant.ocr_boxes import ocr_backend
    from merchant.uia_screen import uia_available

    backend = ocr_backend()
    adapter = get_adapter()

    print(BANNER)
    print(f"  data source     : {adapter.label}")
    print(f"  OCR backend     : {backend or 'NONE'}")
    print(f"  UI Automation   : {'available' if uia_available() else 'not installed'}")
    print()

    if backend:
        print("  Element targeting on the REAL Razorpay dashboard: WORKING")
        print(f"  (via {backend} — reads row labels straight off the screen)")
    else:
        print("  Element targeting on the REAL dashboard: UNAVAILABLE.")
        print("  No OCR engine found, so nothing can be located on a page that")
        print("  does not publish its own layout. The local mock dashboard will")
        print("  still work. Install one with:  pip install rapidocr-onnxruntime")
    print()
    print("  Screen reading is OFF until you press 'Allow screen reading'.")
    print("  Nothing is captured, and no data is read, before you do.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch Clicky Merchant Mode (overlay + panel, no audio).")
    parser.add_argument("--scenario", default=None,
                        help="demo scenario id to start on (see /api/merchant/scenarios)")
    parser.add_argument("--grant", action="store_true",
                        help="grant screen permission at startup (for recording; "
                             "normally the merchant clicks the button)")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    _report_environment()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    from merchant.pipeline import MerchantPipeline, PipelineConfig, PipelineDeps
    from merchant.privacy import PrivacyState
    from ui.merchant_panel import MerchantPanel
    from ui.overlay import CursorOverlay

    privacy = PrivacyState()
    if args.grant:
        privacy.grant_permission()
        print("  Screen permission granted via --grant.\n")

    pipeline = MerchantPipeline(
        PipelineConfig(scenario_id=args.scenario),
        PipelineDeps(privacy=privacy),
    )

    overlay = CursorOverlay()
    overlay.show()

    panel = MerchantPanel(manager=None, pipeline=pipeline)
    panel.overlay = overlay
    panel.show()
    panel.raise_()

    # The overlay seeds its position from the cursor on the first tick; nudging
    # it once here avoids a visible jump on the first question.
    QTimer.singleShot(200, lambda: overlay.set_mode("idle"))

    print("  Running. Close the panel window to quit.\n")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
