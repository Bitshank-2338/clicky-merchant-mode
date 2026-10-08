# Agent Handoff Log — Clicky Merchant Mode

Supervisor: **Claude Opus 5**. Workers: Haiku (bulk/mechanical), Sonnet (integration/debug).
This file records decisions, file ownership and handoffs. Append-only during the build.

---

## Phase 1 — Supervisor findings (Opus)

### Correction to the brief

The brief described Clicky as *"Electron + Python sidecar + FastAPI"*. **That is not what the
repository contains.** Verified against `github.com/Bitshank-2338/clicky-windows` @ `cdbc8ee`:

| Brief said | Actually is |
|---|---|
| Electron shell | **PyQt6** desktop app (`main.py`, `ui/panel.py`, `ui/overlay.py`) |
| Python sidecar over IPC | Single Python process; `CompanionManager` runs an asyncio loop on a QThread |
| FastAPI backend | **No FastAPI anywhere.** No HTTP server at all |
| Electron↔Python bridge | Not applicable |

Consequences, decided by the supervisor:

1. There is no Electron/Python bridge to integrate with, so that risk item is **removed**.
2. The FastAPI sidecar required by the brief **does not exist and is created new** in
   `merchant/server.py`. It runs as a separate process (`python -m merchant.server`) and is
   what the mock dashboard and the evaluation harness talk to.
3. All Merchant Mode logic is pure Python with **no PyQt import**, so it is unit-testable
   headlessly on any machine. PyQt is touched only in `ui/merchant_panel.py`.

### Existing architecture (verified by Haiku audit worker)

- `screen/capture.py` — `capture_all_screens(max_width=1280) -> List[ScreenShot]`. `ScreenShot`
  carries physical size, DPI scale and logical origin, so three coordinate spaces
  (physical / logical / downscaled-JPEG) can be converted. **No active-window capture.**
- `ui/overlay.py` — `CursorOverlay(QWidget)` with `point_at(x, y, label)`, `add_circle`,
  `add_arrow`, `add_underline`, `add_text`, `clear_annotations`. Draws in **logical screen pixels**.
- `ai/base_provider.py` — `BaseLLMProvider.stream_response(user_text, screenshots_b64, history,
  system_prompt, model) -> AsyncIterator[str]` and `health_check() -> bool`.
  `ai/ollama_provider.py` implements it against a local Ollama.
- `tutor_features/ocr.py` — `run_ocr(jpeg_bytes) -> str`. **Text only, no bounding boxes.**
- `skills/__init__.py` — plugin contract: a module exporting
  `SKILL = {"name", "trigger" (regex), "description", "handler": async (manager, transcript) -> str}`.
  `load_all()` imports every `.py` in `skills/`. Triggers are matched *before* the LLM runs.
- `config.py` — module-level singleton `cfg = Config()`; `.env` / `.env.local` loaded from the
  app root.

### Key architectural decision — the `skills/` plugin point

Clicky ships a first-class plugin system whose triggers are evaluated **before** the LLM. Merchant
Mode registers there. This means **Clicky's existing behaviour is untouched**: if the user never
says a merchant phrase, not one line of merchant code executes.

Edits to pre-existing Clicky source files are **additive**, with one exception
noted below:

| File | Change | Destructive? |
|---|---|---|
| `screen/capture.py` | add `capture_active_window()` + `WindowShot` | No — new symbols only |
| `tutor_features/ocr.py` | add `run_ocr_boxes()` | No — new symbol only |
| `config.py` | drop env vars that dotenv set to `""` | No — new loop, no existing line changed |
| `requirements.txt` | append merchant extras | No |
| `.env.example` | append Razorpay + merchant vars | No |
| `audio/capture.py` | add `pcm16_to_float32()` | No — new symbol only |
| `audio/stt/faster_whisper_stt.py` | **rewrote** `_run()` to pass samples | **Yes — see below** |
| `audio/ambient_listener.py` | **rewrote** `_transcribe_tiny()` to pass samples | **Yes — see below** |

The last two are a bug fix, not a Merchant Mode feature, and they are the only
place where existing Clicky logic was replaced rather than extended.

Both handed faster-whisper a path to a temp WAV. faster-whisper decodes
anything that is not already a numpy array by calling
`av.open(..., metadata_errors="ignore")`, and **PyAV 19.0 (3 Oct 2026) removed
that argument**. Since `requirements.txt` carries no upper bound on `av`, any
install from that date forward resolved to PyAV 19 and *all* speech input died
with `TypeError: open() got an unexpected keyword argument 'metadata_errors'`
— reported as clicky-windows issue #24. Clicky already holds 16kHz mono PCM16,
so both sites now pass samples and the decoder is never reached. Pinned by
`tests/test_stt_pyav_independence.py`.

Everything else is new files.

### Key architectural decision — how highlighting avoids hardcoded coordinates

The brief forbids hardcoded coordinates as the only targeting method. Targeting is **three-tier**,
and the server never returns pixel coordinates at all — it returns *semantic* targets
(`target_id` + `anchor_text`). Resolution to pixels happens on the client, which is the only
component that has the screenshot:

1. **`dom_map`** (demo mode only, most accurate) — the mock dashboard POSTs its element rects in
   screen coordinates to `/api/merchant/screen-map`. Exact rects, no OCR error.
2. **`anchor_text`** (primary, works on the real Razorpay dashboard) — OCR with per-word bounding
   boxes (`run_ocr_boxes`) locates the anchor phrase in the screenshot, then the box is converted
   from downscaled-JPEG space to logical screen pixels via the `ScreenShot` metadata.
3. **`vlm`** (last resort) — the vision model is asked for normalised 0–1000 coordinates, which is
   Clicky's existing mechanism.

If all three fail the step is reported as *"I can't see that on screen"* rather than pointing at a
guess. **The model is never allowed to author a pixel coordinate that is presented as fact.**

### Key architectural decision — no invented numbers

Every rupee figure in an explanation comes from `merchant/facts.py`, which does arithmetic over
adapter data. The LLM receives **pre-computed facts** and is only allowed to phrase them. A
post-generation guard (`explain.verify_no_invented_numbers`) rejects any response containing a
currency figure that is not in `facts_used`, and falls back to the deterministic template. This is
enforced by tests.

### Data flow

```
voice/text → skills/merchant_mode.py (trigger match)
           → merchant.pipeline.handle()
               permission gate  → merchant.privacy
               active-window capture → screen.capture.capture_active_window()
               masking          → merchant.masking (before anything leaves the process)
               OCR + boxes      → merchant.ocr_boxes
               page detection   → merchant.page_detect
               intent detection → merchant.intent
               KB retrieval     → merchant.kb
               fact extraction  → merchant.facts (+ adapter: demo | razorpay_test)
               explanation      → merchant.explain (Ollama, else deterministic template)
               targets          → merchant.targeting (semantic, resolved client-side)
               audit            → merchant.audit
           → MerchantResponse (typed) → PyQt panel + overlay + TTS
```

---

## File ownership

Two workers must never hold the same file. Ownership is exclusive for the duration of a task.

| Owner | Files |
|---|---|
| **Opus (supervisor)** | `merchant/models.py`, `merchant/masking.py`, `merchant/facts.py`, `merchant/pipeline.py`, `merchant/confirm.py`, `merchant/explain.py`, `merchant/targeting.py`, `merchant/seed/dashboard_seed.json`, `screen/capture.py`, `tutor_features/ocr.py` |
| **Haiku-A** | `docs/RAZORPAY_RESEARCH.md` |
| **Haiku-B** | `mockdashboard/*` |
| **Haiku-C** | `merchant/knowledge/kb.json`, `docs/KNOWLEDGE_BASE.md` |
| **Haiku-D** | `merchant/evaluation/tasks.json` |
| **Haiku-E** | docs drafts: `docs/PRODUCT_SCOPE.md`, `docs/PRIVACY.md`, `docs/SAFETY.md`, `docs/DEMO_SCRIPT.md`, `docs/KNOWN_LIMITATIONS.md` |
| **Sonnet-A** | `merchant/server.py`, `merchant/adapters/*` |
| **Sonnet-B** | `ui/merchant_panel.py`, `skills/merchant_mode.py` |

---

## Handoff entries

Recorded as each worker completed. Every worker report was **re-verified by the
supervisor** rather than accepted; the verification column says what that found.

| # | Worker | Model | Deliverable | Supervisor verification |
|---|---|---|---|---|
| 1 | Repo audit | Haiku | API inventory of 12 Clicky modules | Spot-checked against source; accurate. Confirmed the brief's Electron/FastAPI description was wrong. |
| 2 | Razorpay research | Haiku | `docs/RAZORPAY_RESEARCH.md` | Checked every KB entry derived from it carries a `razorpay.com` URL — all 31 do. |
| 3 | Mock dashboard | Haiku | `mockdashboard/*` (~1350 lines) | Rendered live in a browser. Found **2 bugs** the worker missed: negative screen coordinates and a nav highlight that never matched the page. Both fixed. |
| 4 | Knowledge base | Haiku | `kb.json` (31 entries), `docs/KNOWLEDGE_BASE.md` | Validated JSON, field completeness, URL host, translations. Hindi/Hinglish quality good. 1 entry correctly marked `verified: false`. |
| 5 | Evaluation dataset | Haiku | `tasks.json` (36 tasks) | Enum values and anchor keys all valid. **Deliberately not edited afterwards** — see below. |
| 6 | Domain unit tests | Haiku | 5 files, 118 tests | All pass. Reported no source bugs, which was correct for its scope. |
| 7 | Documentation drafts | Haiku | scope, privacy, safety, demo script, limitations | Claims traced to code; the worker correctly refused to invent metrics and left them to the supervisor. |
| 8 | Razorpay test adapter | Sonnet | `razorpay_test.py`, `adapters/__init__.py` | Re-ran the read-only grep as a **test** rather than trusting the report; live-key refusal and secret-leak behaviour independently verified. |
| 9 | FastAPI sidecar + eval runner | Sonnet | `server.py`, `evaluation/runner.py` | Correctly diagnosed the `kb.kb_answer` bug, but its evaluation numbers were **stale** (the fix had already landed). Re-run rather than reused. |
| 10 | PyQt panel + skill | Sonnet | `merchant_panel.py`, `merchant_mode.py` | Verified independently. Found the skill left voice-driven "next" unusable; fixed by claiming only merchant-specific next-phrases so `tutor.NEXT_RE` keeps ownership of bare "next". |

### Ownership changes during the build

- `merchant/evaluation/runner.py` — taken over by the supervisor after worker 9
  finished, to add `fallback_success_rate` and `step_completion_rate` (both
  required by the brief and not in the original spec given to the worker).
- `merchant/server.py`, `merchant/adapters/__init__.py` — supervisor made small
  type-hygiene edits after handback.
- `mockdashboard/app.js` — supervisor fixed the two browser-found bugs after
  worker 3 finished.

No two workers ever held the same file concurrently. No worker spawned a worker.
At most three ran at once.

### A deliberate decision about the evaluation dataset

Eight tasks still fail `intent_correct`. Six of those are cases where the
returned intent is defensible and the merchant-facing answer is correct, and one
(`eval_026`) is an outright labelling error in the dataset.

The dataset was **not** edited to fix them. Rewriting the answer key to match the
implementation would turn the metric into a tautology. The headline figure is
reported as measured (77.8%) with the discrepancies itemised in
`docs/EVALUATION_REPORT.md`.

### Bugs the supervisor found that no worker did

Full detail in `docs/BUILD_LOG.md`. The three that mattered most:

1. **A privacy hole** — the permission gate could be bypassed by a caller
   claiming `screen.captured = true`. Verified live: the sidecar returned a
   full settlement breakdown before permission was granted.
2. **A safety miss** — "refund kar de" was not recognised as an instruction to
   act, because the detector used a fixed substring list.
3. **A false positive in the anti-hallucination guard** — the currency pattern
   matched "rs," inside "…the money is yours, failed…", silently deleting a
   correct answer.

Each is now covered by a regression test.
