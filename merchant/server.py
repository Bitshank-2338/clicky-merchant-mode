"""
FastAPI sidecar for Clicky Merchant Mode.

This process owns no screen-capture code of its own — it is a thin HTTP
front door in front of `merchant.pipeline.MerchantPipeline`. Callers are the
mock dashboard (a static demo page that polls `/api/merchant/screen-map` and
posts questions to `/api/merchant/ask`), the desktop companion panel, and the
evaluation harness via `/api/evaluation/run`.

Every endpoint is built to fail soft: a bad request gets FastAPI's normal 422,
a known domain error (an expired or already-used confirmation token) gets a
409 with a small structured body, and anything else is caught by the
module-wide exception handler at the bottom of this file and turned into a
500 with `{"error", "code": "INTERNAL"}` plus an audit entry — no endpoint is
allowed to take the whole process down.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from merchant import kb
from merchant.adapters.demo import list_scenarios, load_seed, ui_anchors
from merchant.audit import AuditLog, KIND_ERROR
from merchant.confirm import ConfirmationError, ConfirmationManager
from merchant.masking import mask_text
from merchant.models import DashboardPage, Intent, ScreenContext
from merchant.ocr_boxes import tesseract_available
from merchant.page_detect import detect_page, page_from_id
from merchant.pipeline import MerchantPipeline, PipelineConfig, PipelineDeps
from merchant.privacy import PrivacyState

__version__ = "0.1.0"

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"


# ── Pydantic request/response models ─────────────────────────────────────────


class ScreenPayload(BaseModel):
    """The shape of screen data posted by a caller, shared by analyze-screen
    and ask. Every field is optional — an absent screen is a valid state."""

    ocr_text: str = ""
    window_title: str = ""
    url_hint: str = ""
    dom_map: Optional[dict[str, list[int]]] = None
    screenshot_width: int = 0
    screenshot_height: int = 0


class AnalyzeScreenResponse(BaseModel):
    page: str
    confidence: float
    signal: str
    evidence: list[str]
    masked_field_count: int


class AskRequest(BaseModel):
    utterance: str
    screen: Optional[ScreenPayload] = None
    scenario_id: Optional[str] = None


class FactModel(BaseModel):
    key: str
    label: str
    value_text: str
    source: str
    raw_value: Optional[float] = None


class HighlightTargetModel(BaseModel):
    target_id: str
    label: str
    anchor_text: str
    strategy: str
    severity: str
    rect: Optional[tuple[int, int, int, int]] = None


class StepModel(BaseModel):
    index: int
    title: str
    why: str
    anchor_text: str = ""
    target_id: str = ""
    done: bool = False
    requires_confirmation: bool = False


class MerchantResponseModel(BaseModel):
    page: str
    intent: str
    language: str
    answer: str
    steps: list[StepModel]
    highlight_targets: list[HighlightTargetModel]
    facts_used: list[FactModel]
    confidence: float
    requires_confirmation: bool
    source_urls: list[str]
    fallback_used: bool
    why_seeing_this: str
    what_next: str
    warnings: list[str]
    uncertainty: list[str]
    adapter_mode: str
    pending_action_id: Optional[str] = None
    request_id: str


class ScenarioModel(BaseModel):
    id: str
    title: str
    description: str = ""
    page: str = "home"
    default: bool = False


class ScenariosResponse(BaseModel):
    scenarios: list[ScenarioModel]
    current: str
    ui_anchors: dict[str, str]


class KnowledgeEntryModel(BaseModel):
    id: str
    topic: str
    title: str
    simple_en: str
    simple_hi: str
    simple_hinglish: str
    source_url: str
    last_reviewed: str
    pages: list[str]
    keywords: list[str]
    verified: bool


class AuditEventModel(BaseModel):
    event_id: str
    at: float
    kind: str
    detail: str
    outcome: str
    actor: str


class ConfirmActionRequest(BaseModel):
    action_id: str
    approve: bool


class AuthorisationModel(BaseModel):
    action_id: str
    kind: str
    approved_at: float
    summary: str
    executed: bool
    execution_note: str


class RejectedResponse(BaseModel):
    status: str = "rejected"


class ConfirmationErrorResponse(BaseModel):
    code: str
    message: str


class RequestConfirmationRequest(BaseModel):
    kind: str
    summary: str
    amount_paise: Optional[int] = None
    customer_name: str = ""
    customer_contact: str = ""


class ConfirmationRequestModel(BaseModel):
    action_id: str
    kind: str
    title: str
    summary: str
    amount_text: str
    masked_customer: str
    expires_in: float
    warning: str
    irreversible: bool = True


class PrivacySnapshotModel(BaseModel):
    capture_allowed: bool
    cloud_allowed: bool
    monitoring: bool
    granted_at: Optional[float] = None
    captures_this_session: int
    masked_fields_this_session: int
    screenshots_stored: int
    last_capture_at: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    adapter_mode: str
    ollama_available: bool
    tesseract_available: bool
    privacy: PrivacySnapshotModel


class ScreenMapRequest(BaseModel):
    page: Optional[str] = None
    map: dict[str, list[int]] = Field(default_factory=dict)
    url: Optional[str] = None


class ScreenMapResponse(BaseModel):
    ok: bool
    count: int


class EvaluationRunRequest(BaseModel):
    limit: Optional[int] = None


class FailureModel(BaseModel):
    id: str
    metric: str
    expected: str
    actual: str


class EvaluationSummaryModel(BaseModel):
    total: int
    by_metric: dict[str, float]
    by_category: dict[str, float]
    hallucination_rate: float
    privacy_violations: int
    sensitive_blocking_rate: float
    fallback_rate: float
    mean_latency_ms: float
    failures: list[FailureModel]
    generated_at: str


class ErrorResponse(BaseModel):
    error: str
    code: str = "INTERNAL"


# ── Ollama integration ────────────────────────────────────────────────────────


def _check_ollama() -> bool:
    """Best-effort local Ollama probe. Never raises, never hangs."""
    try:
        resp = httpx.get(OLLAMA_TAGS_URL, timeout=1.0)
        return resp.status_code == 200
    except Exception:
        return False


async def _ollama_refine(system_prompt: str, user_prompt: str) -> str:
    """Ask the local Ollama model to rephrase a draft answer.

    Raises on any failure (timeout, connection error, bad response shape) —
    the pipeline is responsible for catching that and falling back to the
    deterministic template, so this function must not swallow errors itself.
    """
    model = os.environ.get("MERCHANT_OLLAMA_MODEL", "llama3.2")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(OLLAMA_CHAT_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return str(data["message"]["content"])


# ── Process-wide singletons ───────────────────────────────────────────────────
#
# One process, one merchant session. `PrivacyState`, `AuditLog` and
# `ConfirmationManager` are shared so every endpoint sees the same session
# state, exactly as they would inside the desktop panel.

_privacy = PrivacyState()
_audit = AuditLog()
_confirmations = ConfirmationManager(_audit)

_ollama_available_at_startup = _check_ollama()
_refine_hook = _ollama_refine if _ollama_available_at_startup else None

_pipeline_deps = PipelineDeps(
    privacy=_privacy,
    audit=_audit,
    confirmations=_confirmations,
    refine=_refine_hook,
)
_pipeline = MerchantPipeline(PipelineConfig(), _pipeline_deps)

# Latest screen map POSTed by the mock dashboard (or any other caller). A
# single most-recent snapshot, not a history — capped so a buggy or hostile
# client cannot grow this without bound.
_MAX_SCREEN_MAP_ENTRIES = 200
_latest_screen_map: dict[str, object] = {"page": None, "map": {}, "url": None,
                                         "updated_at": None}


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Clicky Merchant Mode")

# Local-only demo server: this process binds to 127.0.0.1 only (see `main()`
# below) and is never reachable from outside the machine, so a permissive
# CORS policy carries no real exposure — it just lets the mock dashboard
# (served from its own static origin) call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_screen_context(
    payload: Optional[ScreenPayload], fallback_dom_map: bool = False
) -> tuple[ScreenContext, int]:
    """Build a `ScreenContext` from a request payload.

    `ocr_text` is masked before it ever reaches a `ScreenContext` object, per
    the privacy contract in `merchant.masking`. `captured=True` is set
    unconditionally: this process performs no OS-level screen capture of its
    own, so by the time a request reaches here the data was already produced
    by the caller (mock dashboard JS, the desktop companion, or the eval
    harness) — the capture-consent question this flag answers elsewhere in
    the pipeline does not apply to an explicit, single API call.
    """
    ocr_text = payload.ocr_text if payload else ""
    mask_result = mask_text(ocr_text or "")

    # Values arrive from JSON, so they are untrusted in both shape and content;
    # the loop below is what narrows them to real rects.
    raw_dom: dict[str, object] = dict((payload.dom_map if payload else None) or {})
    if not raw_dom and fallback_dom_map:
        stored = _latest_screen_map.get("map")
        if isinstance(stored, dict):
            raw_dom = dict(stored)

    dom_map: dict[str, tuple[int, int, int, int]] = {}
    for key, rect in raw_dom.items():
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            try:
                dom_map[str(key)] = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
            except (TypeError, ValueError):
                continue

    ctx = ScreenContext(
        ocr_text=mask_result.text,
        window_title=(payload.window_title if payload else "") or "",
        url_hint=(payload.url_hint if payload else "") or "",
        dom_map=dom_map,
        screenshot_width=(payload.screenshot_width if payload else 0) or 0,
        screenshot_height=(payload.screenshot_height if payload else 0) or 0,
        captured=True,
        masked_field_count=mask_result.total,
    )
    return ctx, mask_result.total


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> HealthResponse:
    snap = _privacy.snapshot()
    return HealthResponse(
        status="ok",
        version=__version__,
        adapter_mode=_pipeline.adapter.mode.value,
        ollama_available=_check_ollama(),
        tesseract_available=tesseract_available(),
        privacy=PrivacySnapshotModel(**dataclasses.asdict(snap)),
    )


# ── Screen understanding ─────────────────────────────────────────────────────


@app.post("/api/merchant/analyze-screen")
async def analyze_screen(body: ScreenPayload) -> AnalyzeScreenResponse:
    ctx, masked_count = _build_screen_context(body, fallback_dom_map=False)
    detection = detect_page(ctx)
    return AnalyzeScreenResponse(
        page=detection.page.value,
        confidence=detection.confidence,
        signal=detection.signal,
        evidence=list(detection.evidence or []),
        masked_field_count=masked_count,
    )


@app.post("/api/merchant/screen-map")
async def screen_map(body: ScreenMapRequest) -> ScreenMapResponse:
    capped = dict(list(body.map.items())[:_MAX_SCREEN_MAP_ENTRIES])
    _latest_screen_map["page"] = body.page
    _latest_screen_map["map"] = capped
    _latest_screen_map["url"] = body.url
    _latest_screen_map["updated_at"] = time.time()
    return ScreenMapResponse(ok=True, count=len(capped))


# ── Conversation ──────────────────────────────────────────────────────────────


@app.post("/api/merchant/ask")
async def ask(body: AskRequest) -> MerchantResponseModel:
    current_scenario_id = getattr(_pipeline.adapter, "scenario_id", None)
    if body.scenario_id and body.scenario_id != current_scenario_id:
        _pipeline.set_scenario(body.scenario_id)

    ctx, _ = _build_screen_context(body.screen, fallback_dom_map=True)
    response = await _pipeline.ask(body.utterance, ctx)
    return MerchantResponseModel(**response.to_dict())


@app.post("/api/merchant/next-step")
async def next_step() -> MerchantResponseModel:
    response = await _pipeline.ask("next", ScreenContext(captured=True))
    return MerchantResponseModel(**response.to_dict())


@app.get("/api/merchant/scenarios")
async def scenarios() -> ScenariosResponse:
    seed = load_seed()
    scenario_list = [ScenarioModel(**s) for s in list_scenarios(seed)]
    current = getattr(_pipeline.adapter, "scenario_id", "") or ""
    return ScenariosResponse(
        scenarios=scenario_list, current=current, ui_anchors=ui_anchors(seed)
    )


@app.get("/api/merchant/knowledge")
async def knowledge(
    q: Optional[str] = None,
    topic: Optional[str] = None,
    page: Optional[str] = None,
    limit: int = 50,
) -> list[KnowledgeEntryModel]:
    if not q and not topic and not page:
        entries = kb.all_entries()[: max(limit, 0)]
    else:
        page_enum = page_from_id(page) if page else DashboardPage.UNKNOWN
        entries = kb.retrieve(
            q or "", page_enum, Intent.UNKNOWN, topic or "", limit=max(limit, 0)
        )
    return [KnowledgeEntryModel(**e.to_dict()) for e in entries]


@app.get("/api/merchant/audit")
async def audit(limit: int = 100, kind: Optional[str] = None) -> list[AuditEventModel]:
    events = _audit.events(limit=limit, kind=kind)
    return [AuditEventModel(**e.to_dict()) for e in events]


# ── Confirmations ─────────────────────────────────────────────────────────────


@app.post("/api/merchant/request-confirmation")
async def request_confirmation(body: RequestConfirmationRequest) -> ConfirmationRequestModel:
    req = _confirmations.request(
        kind=body.kind,
        summary=body.summary,
        amount_paise=body.amount_paise,
        customer_name=body.customer_name,
        customer_contact=body.customer_contact,
    )
    return ConfirmationRequestModel(**dataclasses.asdict(req))


@app.post("/api/merchant/confirm-action")
async def confirm_action(body: ConfirmActionRequest):
    if not body.approve:
        _confirmations.reject(body.action_id)
        return RejectedResponse()

    try:
        auth = _confirmations.approve(body.action_id)
    except ConfirmationError as exc:
        return JSONResponse(
            status_code=409,
            content=ConfirmationErrorResponse(code=exc.code, message=exc.message).model_dump(),
        )
    return AuthorisationModel(**dataclasses.asdict(auth))


# ── Privacy ───────────────────────────────────────────────────────────────────


@app.post("/api/merchant/stop-monitoring")
async def stop_monitoring() -> PrivacySnapshotModel:
    _pipeline.stop_monitoring()
    return PrivacySnapshotModel(**dataclasses.asdict(_privacy.snapshot()))


@app.post("/api/merchant/grant-permission")
async def grant_permission() -> PrivacySnapshotModel:
    _privacy.grant_permission()
    return PrivacySnapshotModel(**dataclasses.asdict(_privacy.snapshot()))


# ── Evaluation ────────────────────────────────────────────────────────────────


@app.post("/api/evaluation/run")
async def run_evaluation_endpoint(body: EvaluationRunRequest) -> EvaluationSummaryModel:
    import asyncio

    from merchant.evaluation.runner import run_evaluation

    # run_evaluation drives its own asyncio.run(...) internally, which cannot
    # be nested inside this already-running event loop — offload to a thread.
    summary = await asyncio.to_thread(run_evaluation, body.limit)
    return EvaluationSummaryModel(**summary)


# ── Seed passthrough + mock dashboard ────────────────────────────────────────


@app.get("/api/merchant/seed")
async def seed() -> JSONResponse:
    # The seed file's shape is intentionally open-ended (new demo scenarios
    # get added without touching this server), so it is passed through as
    # raw JSON rather than forced into a fixed schema.
    return JSONResponse(content=load_seed())


_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "mockdashboard"
if _DASHBOARD_DIR.is_dir():
    app.mount("/dashboard", StaticFiles(directory=str(_DASHBOARD_DIR), html=True),
              name="dashboard")


# ── Global failure guard ──────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = mask_text(f"{type(exc).__name__}: {exc}").text
    _audit.record(KIND_ERROR, f"unhandled exception on {request.url.path}: {detail}",
                 outcome="error")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error=detail, code="INTERNAL").model_dump(),
    )


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    # 127.0.0.1 ONLY — never 0.0.0.0. This process reads the merchant's
    # screen; binding to every interface would expose that to the LAN.
    uvicorn.run(app, host="127.0.0.1", port=8756)


if __name__ == "__main__":
    main()
