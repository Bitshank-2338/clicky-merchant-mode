"""
Merchant Mode panel — Clicky's friendly, trustworthy UI for shopkeepers.

`MerchantPanel` is a frameless, always-on-top QWidget that matches Clicky's
existing visual language (see `ui.panel.CompanionPanel` / `ui.design`). It is
constructible with `manager=None` so it can be smoke-tested standalone:

    python -c "from PyQt6.QtWidgets import QApplication; import sys; \
        a = QApplication(sys.argv); from ui.merchant_panel import MerchantPanel; \
        p = MerchantPanel(); print('ok')"

The panel drives a `merchant.pipeline.MerchantPipeline` (created internally
when one is not supplied), never fabricates a coordinate to point at, never
performs a sensitive action itself, and never blocks the Qt GUI thread —
`MerchantPipeline.ask()` runs on a background `QThread`.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Optional, Protocol, Sequence

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from merchant.adapters.demo import list_scenarios
from merchant.confirm import ConfirmationRequest
from merchant.masking import mask_text
from merchant.models import (
    DashboardPage,
    MerchantResponse,
    ScreenContext,
    Step,
    WordBox,
)
from merchant.ocr_boxes import extract_word_boxes, ocr_backend, text_from_boxes
from merchant.pipeline import MerchantPipeline
from merchant.privacy import PrivacySnapshot
from merchant.targeting import ResolvedTarget, ScreenGeometry, resolve_all, summarise

from ui.design import (
    BORDER,
    ERROR,
    PANEL_RADIUS,
    SUCCESS,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    font,
)
from ui.overlay import CursorOverlay

PANEL_W = 420
PANEL_H = 760


class ManagerLike(Protocol):
    """The subset of CompanionManager the panel actually calls.

    Declared structurally so this module never imports `companion_manager`
    (which pulls in audio/AI stacks) and so `MerchantPanel(manager=None)`
    stays a fully supported configuration.
    """

    def on_hotkey_press(self) -> None: ...

    def on_hotkey_release(self) -> None: ...


def _css(color: QColor) -> str:
    return f"rgb({color.red()},{color.green()},{color.blue()})"


def _capture_screen_context(
    pipeline: MerchantPipeline,
) -> tuple[ScreenContext, Optional[ScreenGeometry], list[WordBox]]:
    """Best-effort active-window capture, masked before it leaves this function.

    Returns an empty, uncaptured `ScreenContext` whenever permission has not
    been granted or capture fails for any reason — the pipeline handles that
    honestly (it asks for permission or says it cannot see the screen), so
    this function never raises.
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
    # Any available OCR engine will do — Tesseract if installed, otherwise the
    # pip-only RapidOCR. Gating on Tesseract alone left the real dashboard
    # unreadable on a machine that had never run its Windows installer.
    if ocr_backend():
        try:
            image_bytes = base64.b64decode(shot.base64_jpeg)
            word_boxes = extract_word_boxes(image_bytes)
        except Exception:
            word_boxes = []

    # Mask every word individually before it is ever attached to a context
    # object — matches merchant.privacy's rule that screen text is masked
    # before it leaves the function that produced it.
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


# How long the cursor rests on one element before flying to the next. The
# overlay's flight alone is ~1.8s, so anything shorter cuts the animation off.
POINT_DWELL_MS = 2600


class _AskWorker(QThread):
    """Runs `MerchantPipeline.ask()` off the GUI thread and reports back."""

    finished_ok = pyqtSignal(object)   # MerchantResponse
    finished_err = pyqtSignal(str)

    def __init__(self, pipeline: MerchantPipeline, utterance: str,
                 screen: ScreenContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._utterance = utterance
        self._screen = screen

    def run(self) -> None:
        try:
            response = asyncio.run(self._pipeline.ask(self._utterance, self._screen))
        except Exception as exc:
            self.finished_err.emit(str(exc))
            return
        self.finished_ok.emit(response)


class ConfirmationDialog(QDialog):
    """Modal shown before any sensitive action.

    Renders a `merchant.confirm.ConfirmationRequest`: the action title, the
    summary, the exact amount, the masked customer, the warning text, and a
    live countdown. "Yes, I confirm" stays disabled for the first two seconds
    so it cannot be clicked reflexively, and the dialog auto-rejects when the
    countdown reaches zero. Escape rejects it too.
    """

    CONFIRM_DELAY_MS = 2000

    def __init__(self, request: ConfirmationRequest, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.request = request
        self._remaining: float = max(0.0, request.expires_in)

        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(True)
        self.setObjectName("confirm_dialog")
        self.setStyleSheet(
            "QDialog#confirm_dialog {"
            f"background-color: {_css(SURFACE)};"
            f"border: 1px solid {_css(BORDER)}; border-radius: {PANEL_RADIUS}px; }}"
            f"QLabel {{ color: {_css(TEXT_PRIMARY)}; background: transparent; }}"
        )
        self.setFixedWidth(360)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        title_lbl = QLabel(request.title)
        title_lbl.setFont(font(16, QFont.Weight.Bold))
        root.addWidget(title_lbl)

        summary_lbl = QLabel(request.summary)
        summary_lbl.setWordWrap(True)
        root.addWidget(summary_lbl)

        amount_row = QHBoxLayout()
        amount_key = QLabel("Amount")
        amount_key.setStyleSheet(f"color: {_css(TEXT_SECONDARY)};")
        amount_val = QLabel(request.amount_text)
        amount_val.setFont(font(15, QFont.Weight.Bold))
        amount_row.addWidget(amount_key)
        amount_row.addStretch()
        amount_row.addWidget(amount_val)
        root.addLayout(amount_row)

        customer_row = QHBoxLayout()
        customer_key = QLabel("Customer")
        customer_key.setStyleSheet(f"color: {_css(TEXT_SECONDARY)};")
        customer_val = QLabel(request.masked_customer)
        customer_row.addWidget(customer_key)
        customer_row.addStretch()
        customer_row.addWidget(customer_val)
        root.addLayout(customer_row)

        warning_lbl = QLabel(request.warning)
        warning_lbl.setWordWrap(True)
        warning_lbl.setStyleSheet(f"color: {_css(WARNING)}; font-size: 12px;")
        root.addWidget(warning_lbl)

        self._countdown_lbl = QLabel()
        self._countdown_lbl.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 11px;")
        root.addWidget(self._countdown_lbl)

        btn_row = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setDefault(True)
        self._cancel_btn.setAutoDefault(True)
        self._cancel_btn.setToolTip("Cancel — nothing happens")
        self._cancel_btn.setAccessibleName("Cancel confirmation")
        self._cancel_btn.clicked.connect(self.reject)

        self._confirm_btn = QPushButton("Yes, I confirm")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.setToolTip("Confirm this action")
        self._confirm_btn.setAccessibleName("Confirm action")
        self._confirm_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_css(ERROR)}; color: white; "
            "font-weight: 600; border-radius: 8px; padding: 6px 14px; }"
            "QPushButton:disabled { background-color: rgba(255,70,70,90); "
            "color: rgba(255,255,255,150); }"
        )
        self._confirm_btn.clicked.connect(self.accept)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._confirm_btn)
        root.addLayout(btn_row)

        self._cancel_btn.setFocus()

        self._enable_timer = QTimer(self)
        self._enable_timer.setSingleShot(True)
        self._enable_timer.timeout.connect(self._enable_confirm)
        self._enable_timer.start(self.CONFIRM_DELAY_MS)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(1000)
        self._update_countdown()

    def _enable_confirm(self) -> None:
        self._confirm_btn.setEnabled(True)

    def _on_tick(self) -> None:
        self._remaining = max(0.0, self._remaining - 1.0)
        self._update_countdown()
        if self._remaining <= 0:
            self._tick_timer.stop()
            self.reject()

    def _update_countdown(self) -> None:
        self._countdown_lbl.setText(f"This expires in {int(self._remaining)}s.")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class MerchantPanel(QWidget):
    """Floating Merchant Mode control panel."""

    def __init__(
        self,
        manager: Optional[ManagerLike] = None,
        pipeline: Optional[MerchantPipeline] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._manager: Optional[ManagerLike] = manager
        self._pipeline: MerchantPipeline = pipeline or MerchantPipeline()

        # Set from outside (e.g. main.py) when a live CursorOverlay exists.
        # highlight() also accepts an overlay explicitly, so this is only
        # used to auto-highlight after the panel's own "Ask" flow.
        self.overlay: Optional[CursorOverlay] = None

        self._worker: Optional[_AskWorker] = None
        self._uncertainty_lines: list[str] = []
        self._last_geo: Optional[ScreenGeometry] = None
        self._last_word_boxes: list[WordBox] = []
        self._last_dom_map: dict[str, tuple[int, int, int, int]] = {}
        self._pending_points: list[ResolvedTarget] = []
        self._point_overlay: Optional[CursorOverlay] = None

        self._setup_window()
        self._build_ui()
        self._position_bottom_right()
        self._refresh_privacy_strip()

    # ── Window setup ─────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("merchant_panel")
        self.setFixedSize(PANEL_W, PANEL_H)

    def _position_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        x = geo.right() - PANEL_W - 24
        y = geo.bottom() - PANEL_H - 60
        self.move(x, y)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(18, 18, 22, 235)))
        painter.setPen(QPen(QColor(60, 60, 75, 180), 1))
        painter.drawRoundedRect(self.rect(), PANEL_RADIUS, PANEL_RADIUS)
        painter.end()

    # ── Layout assembly ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        root.addWidget(self._build_header())

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: rgba(60,60,75,180);")
        root.addWidget(div)

        root.addWidget(self._build_privacy_strip())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 4, 0)
        body_layout.setSpacing(14)
        body_layout.addWidget(self._build_language_row())
        body_layout.addWidget(self._build_page_row())
        body_layout.addWidget(self._build_input_row())
        body_layout.addWidget(self._build_answer_card())
        body_layout.addWidget(self._build_why_next_section())
        body_layout.addWidget(self._build_steps_section())
        body_layout.addWidget(self._build_uncertainty_section())
        body_layout.addWidget(self._build_audit_section())
        body_layout.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        root.addWidget(self._build_footer())

    # ── Section 1: header ────────────────────────────────────────────────────

    def _badge_text(self) -> str:
        return "DEMO MODE" if self._pipeline.adapter.mode.value == "demo" else "TEST MODE"

    def _build_header(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Merchant Mode")
        title.setFont(font(15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_css(TEXT_PRIMARY)};")

        self._mode_badge = QLabel(self._badge_text())
        self._mode_badge.setStyleSheet(
            "background: rgba(0,120,255,25); border: 1px solid rgba(0,120,255,100);"
            "border-radius: 8px; color: rgb(140,180,255); font-size: 11px; padding: 2px 8px;"
        )

        close_btn = QPushButton("—")
        close_btn.setFixedSize(24, 24)
        close_btn.setToolTip("Hide panel")
        close_btn.setAccessibleName("Minimize Merchant Mode panel")
        close_btn.setStyleSheet(
            "QPushButton { background: rgba(60,60,75,180); color: rgb(220,220,230);"
            "border: none; border-radius: 12px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(80,80,95,220); }"
        )
        close_btn.clicked.connect(self.hide)

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self._mode_badge)
        layout.addWidget(close_btn)
        return row

    # ── Section 2: privacy strip ─────────────────────────────────────────────

    def _build_privacy_strip(self) -> QWidget:
        box = QFrame()
        box.setObjectName("privacy_strip")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self._privacy_indicator = QLabel()
        self._privacy_indicator.setWordWrap(True)
        self._allow_btn = QPushButton("Allow screen reading")
        self._allow_btn.setToolTip("Grant Merchant Mode permission to read the active window")
        self._allow_btn.setAccessibleName("Allow screen reading")
        self._allow_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_css(WARNING)}; color: rgb(30,25,10);"
            "font-weight: 600; border-radius: 8px; padding: 4px 10px; }"
        )
        self._allow_btn.clicked.connect(self._on_allow_clicked)
        top_row.addWidget(self._privacy_indicator, 1)
        top_row.addWidget(self._allow_btn)
        layout.addLayout(top_row)

        counts_row = QHBoxLayout()
        self._masked_label = QLabel()
        self._masked_label.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 11px;")
        self._screenshots_label = QLabel("Screenshots saved: 0")
        self._screenshots_label.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 11px;")
        counts_row.addWidget(self._masked_label)
        counts_row.addStretch()
        counts_row.addWidget(self._screenshots_label)
        layout.addLayout(counts_row)

        self._stop_btn = QPushButton("Stop monitoring")
        self._stop_btn.setToolTip("Immediately stop all screen reading")
        self._stop_btn.setAccessibleName("Stop monitoring")
        self._stop_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_css(ERROR)}; color: white; font-weight: 700;"
            "border-radius: 8px; padding: 8px 12px; }"
            "QPushButton:hover { background-color: rgb(220,50,60); }"
        )
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self._stop_btn)

        return box

    def _refresh_privacy_strip(self) -> None:
        snap: PrivacySnapshot = self._pipeline.deps.privacy.snapshot()
        if snap.capture_allowed:
            self._privacy_indicator.setText(f"● {snap.status_text()}")
            self._privacy_indicator.setStyleSheet(
                f"color: {_css(SUCCESS)}; font-weight: 600; font-size: 12px;"
            )
            self._allow_btn.setVisible(False)
        else:
            self._privacy_indicator.setText(snap.status_text())
            self._privacy_indicator.setStyleSheet(
                f"color: {_css(WARNING)}; font-size: 12px;"
            )
            self._allow_btn.setVisible(True)
        self._masked_label.setText(f"Masked fields this session: {snap.masked_fields_this_session}")
        self._screenshots_label.setText("Screenshots saved: 0")

    def _on_allow_clicked(self) -> None:
        self._pipeline.deps.privacy.grant_permission()
        self._refresh_privacy_strip()

    def _on_stop_clicked(self) -> None:
        self._pipeline.stop_monitoring()
        self._refresh_privacy_strip()

    # ── Section 3: language selector ─────────────────────────────────────────

    def _build_language_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Language:")
        lbl.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 12px;")
        self._language_combo = QComboBox()
        self._language_combo.addItem("Auto", userData="auto")
        self._language_combo.addItem("English", userData="english")
        self._language_combo.addItem("हिन्दी", userData="hindi")
        self._language_combo.addItem("Hinglish", userData="hinglish")
        self._language_combo.setToolTip(
            "Auto uses Merchant Mode's own language detection from what you type "
            "or say. Other choices are recorded here for display only."
        )
        self._language_combo.setAccessibleName("Merchant Mode language")
        layout.addWidget(lbl)
        layout.addWidget(self._language_combo, 1)
        return row

    # ── Section 4: page detector ─────────────────────────────────────────────

    def _build_page_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        self._page_label = QLabel("Detected page: —")
        self._page_label.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 11px;")
        layout.addWidget(self._page_label)
        layout.addStretch()
        return row

    def _update_page_label(self, page: DashboardPage, confidence: float) -> None:
        pct = int(round(max(0.0, min(1.0, confidence)) * 100))
        label = page.value.replace("_", " ").title()
        self._page_label.setText(f"Detected page: {label} ({pct}% confidence)")

    # ── Section 5: input row ─────────────────────────────────────────────────

    def _build_input_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Mere payment ka settlement kam kyon aaya?")
        self._input.setAccessibleName("Ask Merchant Mode a question")
        self._input.returnPressed.connect(self._on_ask_clicked)

        self._ask_btn = QPushButton("Ask")
        self._ask_btn.setToolTip("Ask Merchant Mode this question")
        self._ask_btn.setAccessibleName("Ask")
        self._ask_btn.clicked.connect(self._on_ask_clicked)

        self._voice_btn = QPushButton("\U0001F3A4 Voice")
        self._voice_btn.setAccessibleName("Hold to speak to Merchant Mode")
        if self._manager is None:
            self._voice_btn.setEnabled(False)
            self._voice_btn.setToolTip(
                "Voice input needs a running Clicky session (no manager attached)."
            )
        else:
            self._voice_btn.setToolTip("Hold to speak, release to send")
            self._voice_btn.pressed.connect(self._on_voice_pressed)
            self._voice_btn.released.connect(self._on_voice_released)

        layout.addWidget(self._input, 1)
        layout.addWidget(self._ask_btn)
        layout.addWidget(self._voice_btn)
        return row

    def _on_voice_pressed(self) -> None:
        if self._manager is not None:
            self._manager.on_hotkey_press()

    def _on_voice_released(self) -> None:
        if self._manager is not None:
            self._manager.on_hotkey_release()

    # ── Section 6: explanation card ──────────────────────────────────────────

    def _build_answer_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("answer_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        self._answer_label = QLabel("Ask a question about your dashboard to get started.")
        self._answer_label.setWordWrap(True)
        self._answer_label.setFont(font(15))
        self._answer_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._answer_label.setStyleSheet(f"color: {_css(TEXT_PRIMARY)};")
        layout.addWidget(self._answer_label)
        return card

    # ── Section 7: why / what next ───────────────────────────────────────────

    def _build_why_next_section(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._why_box = QWidget()
        why_layout = QVBoxLayout(self._why_box)
        why_layout.setContentsMargins(0, 0, 0, 0)
        why_title = QLabel("Why am I seeing this?")
        why_title.setFont(font(12, QFont.Weight.DemiBold))
        why_title.setStyleSheet(f"color: {_css(TEXT_SECONDARY)};")
        self._why_content = QLabel()
        self._why_content.setWordWrap(True)
        why_layout.addWidget(why_title)
        why_layout.addWidget(self._why_content)
        self._why_box.setVisible(False)

        self._next_box = QWidget()
        next_layout = QVBoxLayout(self._next_box)
        next_layout.setContentsMargins(0, 0, 0, 0)
        next_title = QLabel("What should I do next?")
        next_title.setFont(font(12, QFont.Weight.DemiBold))
        next_title.setStyleSheet(f"color: {_css(TEXT_SECONDARY)};")
        self._next_content = QLabel()
        self._next_content.setWordWrap(True)
        next_layout.addWidget(next_title)
        next_layout.addWidget(self._next_content)
        self._next_box.setVisible(False)

        layout.addWidget(self._why_box)
        layout.addWidget(self._next_box)
        return box

    # ── Section 8: step checklist ────────────────────────────────────────────

    def _build_steps_section(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel("Steps")
        header.setFont(font(12, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {_css(TEXT_SECONDARY)};")
        layout.addWidget(header)

        self._steps_container = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_container)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(8)
        layout.addWidget(self._steps_container)

        self._step_btn = QPushButton("Mark done / Next step")
        self._step_btn.setToolTip("Advance the current guide to its next step")
        self._step_btn.setAccessibleName("Mark current step done and advance")
        self._step_btn.clicked.connect(self._on_next_step_clicked)
        layout.addWidget(self._step_btn)

        box.setVisible(False)
        self._steps_box = box
        return box

    def _render_steps(self, steps: list[Step]) -> None:
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not steps:
            self._steps_box.setVisible(False)
            return

        current_index = next((i for i, s in enumerate(steps) if not s.done), len(steps))
        for i, step in enumerate(steps):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            dot = QLabel("●")
            if step.done:
                dot_color = SUCCESS
            elif i == current_index:
                dot_color = WARNING
            else:
                dot_color = TEXT_SECONDARY
            dot.setStyleSheet(f"color: {_css(dot_color)}; font-size: 11px;")

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            title_lbl = QLabel(step.title)
            title_lbl.setWordWrap(True)
            title_lbl.setFont(font(13, QFont.Weight.Medium))
            title_lbl.setStyleSheet(f"color: {_css(TEXT_PRIMARY)};")
            text_col.addWidget(title_lbl)
            if step.why:
                why_lbl = QLabel(step.why)
                why_lbl.setWordWrap(True)
                why_lbl.setFont(font(11))
                why_lbl.setStyleSheet(f"color: {_css(TEXT_SECONDARY)};")
                text_col.addWidget(why_lbl)

            row_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row_layout.addLayout(text_col, 1)
            self._steps_layout.addWidget(row)

        self._steps_box.setVisible(True)

    def _on_next_step_clicked(self) -> None:
        self._submit_question("next")

    # ── Section 9: uncertainty / warnings ────────────────────────────────────

    def _build_uncertainty_section(self) -> QWidget:
        box = QFrame()
        box.setObjectName("uncertainty_box")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self._uncertainty_label = QLabel()
        self._uncertainty_label.setWordWrap(True)
        self._uncertainty_label.setStyleSheet(f"color: {_css(WARNING)}; font-size: 12px;")
        layout.addWidget(self._uncertainty_label)
        box.setVisible(False)
        self._uncertainty_box = box
        return box

    def _render_uncertainty(self, warnings: list[str], uncertainty: list[str]) -> None:
        self._uncertainty_lines = [f"⚠ {w}" for w in warnings] + \
            [f"⚠ {u}" for u in uncertainty]
        self._refresh_uncertainty_box()

    def _append_uncertainty(self, text: str) -> None:
        self._uncertainty_lines.append(f"⚠ {text}")
        self._refresh_uncertainty_box()

    def _refresh_uncertainty_box(self) -> None:
        if not self._uncertainty_lines:
            self._uncertainty_box.setVisible(False)
            return
        self._uncertainty_label.setText("\n".join(self._uncertainty_lines))
        self._uncertainty_box.setVisible(True)

    # ── Section 10: audit panel ──────────────────────────────────────────────

    def _build_audit_section(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        self._audit_toggle_btn = QPushButton("▸ Audit log")
        self._audit_toggle_btn.setFlat(True)
        self._audit_toggle_btn.setCheckable(True)
        self._audit_toggle_btn.setToolTip("Show or hide the audit log")
        self._audit_toggle_btn.setAccessibleName("Toggle audit log")
        self._audit_toggle_btn.setStyleSheet(
            f"QPushButton {{ color: {_css(TEXT_SECONDARY)}; text-align: left; border: none; }}"
        )
        self._audit_toggle_btn.clicked.connect(self._on_audit_toggle)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Reload recent audit events")
        refresh_btn.setAccessibleName("Refresh audit log")
        refresh_btn.clicked.connect(self._refresh_audit)

        header_row.addWidget(self._audit_toggle_btn)
        header_row.addStretch()
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        self._audit_list = QListWidget()
        self._audit_list.setVisible(False)
        self._audit_list.setMaximumHeight(150)
        self._audit_list.setStyleSheet(
            f"QListWidget {{ background: rgba(255,255,255,8); border: 1px solid "
            f"{_css(BORDER)}; border-radius: 8px; color: {_css(TEXT_SECONDARY)}; "
            "font-size: 11px; }"
        )
        layout.addWidget(self._audit_list)

        return box

    def _on_audit_toggle(self) -> None:
        checked = self._audit_toggle_btn.isChecked()
        self._audit_list.setVisible(checked)
        self._audit_toggle_btn.setText("▾ Audit log" if checked else "▸ Audit log")
        if checked:
            self._refresh_audit()

    def _refresh_audit(self) -> None:
        self._audit_list.clear()
        for event in self._pipeline.deps.audit.events(limit=20):
            stamp = time.strftime("%H:%M:%S", time.localtime(event.at))
            text = f"{stamp}  [{event.kind}]  {event.detail}"
            self._audit_list.addItem(QListWidgetItem(text))

    # ── Section 11: footer ───────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        disclaimer = QLabel("Independent hackathon prototype. Not an official Razorpay product.")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 10px;")
        layout.addWidget(disclaimer)

        scenario_row = QHBoxLayout()
        lbl = QLabel("Scenario:")
        lbl.setStyleSheet(f"color: {_css(TEXT_SECONDARY)}; font-size: 11px;")
        self._scenario_combo = QComboBox()
        self._scenario_combo.setAccessibleName("Demo scenario")
        for scenario in list_scenarios():
            self._scenario_combo.addItem(scenario["title"], userData=scenario["id"])
        self._scenario_combo.currentIndexChanged.connect(self._on_scenario_changed)
        scenario_row.addWidget(lbl)
        scenario_row.addWidget(self._scenario_combo, 1)
        layout.addLayout(scenario_row)

        return box

    def _on_scenario_changed(self, _index: int) -> None:
        scenario_id = self._scenario_combo.currentData()
        if not scenario_id:
            return
        self._pipeline.set_scenario(str(scenario_id))
        self._render_steps([])
        self._update_page_label(DashboardPage.UNKNOWN, 0.0)
        self._answer_label.setText("Scenario changed. Ask a question about this screen.")
        self._render_uncertainty([], [])

    # ── Ask flow ──────────────────────────────────────────────────────────────

    def _on_ask_clicked(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._submit_question(text)

    def _submit_question(self, text: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._ask_btn.setEnabled(False)
        self._answer_label.setText("Thinking…")

        ctx, geo, word_boxes = _capture_screen_context(self._pipeline)
        self._last_geo = geo
        self._last_word_boxes = word_boxes
        self._last_dom_map = dict(ctx.dom_map)

        self._worker = _AskWorker(self._pipeline, text, ctx, self)
        self._worker.finished_ok.connect(self._on_ask_success)
        self._worker.finished_err.connect(self._on_ask_error)
        self._worker.start()

    def _on_ask_success(self, response: MerchantResponse) -> None:
        self._ask_btn.setEnabled(True)
        self._input.clear()

        self._answer_label.setText(response.answer or "(no answer)")
        self._why_content.setText(response.why_seeing_this)
        self._why_box.setVisible(bool(response.why_seeing_this))
        self._next_content.setText(response.what_next)
        self._next_box.setVisible(bool(response.what_next))
        self._render_steps(response.steps)
        self._render_uncertainty(list(response.warnings), list(response.uncertainty))
        self._update_page_label(response.page, response.confidence)
        self._mode_badge.setText(self._badge_text())
        self._refresh_privacy_strip()

        if self.overlay is not None and response.highlight_targets:
            self.highlight(
                response, self.overlay, self._last_geo, self._last_word_boxes,
                self._last_dom_map,
            )

        if response.requires_confirmation and response.pending_action_id:
            self._show_confirmation(response.pending_action_id)

    def _on_ask_error(self, message: str) -> None:
        self._ask_btn.setEnabled(True)
        self._answer_label.setText(
            "Something went wrong while I was thinking about that. Please try again."
        )
        self._render_uncertainty([], [message])

    # ── Confirmation flow ─────────────────────────────────────────────────────

    def _show_confirmation(self, action_id: str) -> None:
        confirmations = self._pipeline.deps.confirmations
        if confirmations is None:
            return
        pending = confirmations.get(action_id)
        if pending is None:
            return

        remaining = max(0.0, pending.expires_at - time.time())
        request = ConfirmationRequest(
            action_id=pending.action_id,
            kind=pending.kind,
            title=pending.kind.replace("_", " ").title(),
            summary=pending.summary,
            amount_text=pending.amount_text,
            masked_customer=pending.masked_customer,
            expires_in=remaining,
            warning="Please check the details carefully — this may not be reversible.",
        )
        dialog = ConfirmationDialog(request, self)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            try:
                confirmations.approve(action_id)
            except Exception:
                pass
        else:
            confirmations.reject(action_id)
        self._refresh_audit()

    # ── Highlighting ──────────────────────────────────────────────────────────

    def highlight(
        self,
        response: MerchantResponse,
        overlay: CursorOverlay,
        geo: Optional[ScreenGeometry],
        word_boxes: Optional[Sequence[WordBox]],
        dom_map: Optional[dict[str, tuple[int, int, int, int]]],
    ) -> None:
        """Point at every resolvable highlight target; never guess a pixel.

        Targets that resolve (`ResolvedTarget.found`) get a real `point_at` +
        `add_circle` on the overlay. Targets that do not resolve are folded
        into the uncertainty area via `merchant.targeting.summarise` instead
        of being pointed at.
        """
        uia_lookup = None
        try:
            from merchant.uia_screen import make_lookup

            uia_lookup = make_lookup()
        except Exception:
            uia_lookup = None

        resolved: list[ResolvedTarget] = resolve_all(
            response.highlight_targets, geo=geo, word_boxes=word_boxes,
            dom_map=dom_map, uia_lookup=uia_lookup,
        )

        # Visit the targets one at a time. Calling `point_at` in a loop looks
        # like a bug on screen: each call restarts the cursor's flight, so only
        # the last target is ever actually pointed at. Walking them in sequence
        # is also the honest presentation — the merchant is meant to follow the
        # deduction from gross to net, not see five rings appear at once.
        self._pending_points = [item for item in resolved if item.found]
        self._point_overlay = overlay
        overlay.clear_annotations()
        self._advance_pointer()

        summary = summarise(resolved)
        if summary:
            self._append_uncertainty(summary)

    def _advance_pointer(self) -> None:
        """Point at the next resolved target, then schedule the one after."""
        overlay = self._point_overlay
        if overlay is None or not self._pending_points:
            return

        item = self._pending_points.pop(0)
        cx, cy = item.center
        overlay.point_at(cx, cy, item.target.label)
        radius = max(item.width, item.height, 24.0) / 2.0 + 6.0
        overlay.add_circle(cx, cy, radius, ttl=float(POINT_DWELL_MS) / 1000.0 * 3)

        if self._pending_points:
            QTimer.singleShot(POINT_DWELL_MS, self._advance_pointer)


__all__ = ["MerchantPanel", "ConfirmationDialog", "ManagerLike"]
