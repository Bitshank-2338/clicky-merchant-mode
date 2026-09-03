# Architecture — Clicky Merchant Mode

Independent hackathon prototype. Not an official Razorpay product.

---

## 1. What was already there

Merchant Mode is built on **Clicky**, an existing open-source Windows desktop
AI companion (`github.com/Bitshank-2338/clicky-windows`).

One correction to the brief up front, because it changes the design: the brief
described Clicky as *"Electron + a Python sidecar + FastAPI"*. It is not. The
repository at commit `cdbc8ee` is a **single-process PyQt6 application**:

| Component | File | What it does |
|---|---|---|
| App bootstrap | `main.py` | Qt app, logging, wires everything together |
| Orchestrator | `companion_manager.py` | asyncio loop on a QThread; owns state machine |
| Floating panel | `ui/panel.py` | `CompanionPanel(QWidget)`, frameless, always-on-top |
| Cursor overlay | `ui/overlay.py` | `CursorOverlay(QWidget)`; `point_at`, `add_circle`, `add_arrow` |
| Screen capture | `screen/capture.py` | `mss`-based multi-monitor grab |
| LLM providers | `ai/*.py` | `BaseLLMProvider.stream_response(...)`; Ollama, Claude, OpenAI, Gemini, LM Studio |
| Voice | `audio/stt/*`, `audio/tts/*` | `BaseSTT.transcribe`, `BaseTTS.speak` |
| Plugins | `skills/__init__.py` | Trigger-regex plugin system, matched **before** the LLM |

There is no Electron, no IPC bridge and no HTTP server anywhere in it.

Consequences:

- The Electron↔Python integration risk in the brief **does not exist**.
- The FastAPI sidecar the brief requires **did not exist and was created new**
  (`merchant/server.py`). It is a genuinely separate process.

## 2. How Merchant Mode attaches without touching Clicky

Clicky ships a plugin system whose triggers are evaluated *before* the LLM runs.
Merchant Mode registers there. If the merchant never says a merchant phrase, not
one line of merchant code executes and Clicky behaves exactly as before.

The entire footprint on pre-existing files is **four additive changes**:

| File | Change | Existing code touched? |
|---|---|---|
| `screen/capture.py` | added `WindowShot`, `active_window_rect()`, `capture_active_window()` | No — new symbols appended |
| `requirements.txt` | appended `fastapi`, `uvicorn`, `pytest` | No |
| `.env.example` | appended optional merchant variables | No |
| `skills/merchant_mode.py` | new file (auto-discovered by `load_all()`) | No |

Everything else lives in new directories: `merchant/`, `mockdashboard/`,
`ui/merchant_panel.py`, `tests/`, `docs/`.

`tutor.py`'s `NEXT_RE` owns the bare words "next" and "continue" for Clicky's own
lessons, and it is checked before skills are. So the merchant skill deliberately
claims only longer phrases — "next step", "aage", "agla step", "ho gaya" — and
never shadows Clicky's existing command.

## 3. The merchant package

Pure Python. **No PyQt import anywhere in `merchant/`**, which is why the whole
domain layer is unit-testable headlessly and the evaluation harness can drive
exactly the same code the desktop panel does.

```
merchant/
  models.py        typed contracts (Money in integer paise, MerchantResponse, …)
  masking.py       PII masking — the single chokepoint
  privacy.py       permission gate + session privacy state
  audit.py         append-only masked audit trail
  confirm.py       single-use, expiring confirmation tokens
  facts.py         ALL money arithmetic
  kb.py            knowledge-base retrieval
  knowledge/kb.json  31 curated cards, each with an official source URL
  intent.py        intent + language detection (EN / HI / Hinglish)
  page_detect.py   which dashboard page is on screen
  ocr_boxes.py     per-word OCR bounding boxes
  targeting.py     three-tier semantic target → screen pixels
  explain.py       deterministic templates + the anti-hallucination guard
  pipeline.py      orchestration and every honesty decision
  server.py        FastAPI sidecar (127.0.0.1:8756)
  adapters/        demo (seeded) | razorpay_test (read-only)
  seed/            dashboard_seed.json — shared with the mock dashboard
  evaluation/      tasks.json + runner.py
```

## 4. The pipeline

```
utterance
  │
  ├─ 1. permission gate ────────── merchant.privacy
  │       no consent → stop here. Nothing is read, no data is touched.
  │
  ├─ 2. action-demand refusal ──── merchant.pipeline._detect_action_demand
  │       "refund kar de" → refuse + teach. Never act.
  │
  ├─ 3. active-window capture ──── screen.capture.capture_active_window
  │       one window only, bytes in memory, never written to disk
  │
  ├─ 4. masking ────────────────── merchant.masking.mask_text
  │       before the text reaches a model, a log, or the UI
  │
  ├─ 5. OCR + word boxes ───────── merchant.ocr_boxes.extract_word_boxes
  │
  ├─ 6. page detection ─────────── merchant.page_detect  (dom_map → url → OCR)
  ├─ 7. intent + language ──────── merchant.intent
  ├─ 8. knowledge retrieval ────── merchant.kb
  ├─ 9. fact extraction ────────── merchant.facts   ← every rupee figure
  ├─ 10. explanation ───────────── merchant.explain  (template, then optional
  │                                                   local-model rewording)
  ├─ 11. guard ─────────────────── explain.verify_no_invented_numbers
  ├─ 12. semantic targets ──────── merchant.explain.*_targets
  ├─ 13. audit ─────────────────── merchant.audit
  ▼
MerchantResponse  →  panel + overlay + TTS
                  →  client-side targeting resolves targets to pixels
```

## 5. Three decisions that shaped everything

### 5.1 The model may not author a number

`merchant/facts.py` does every calculation, in **integer paise** — never floats,
because money arithmetic must be exact. It hands the explanation layer a list of
`Fact` objects, each carrying the exact rendered string
(`Fact(key="fees", value_text="₹200", …)`).

`explain.verify_no_invented_numbers(answer, facts)` then extracts every currency
figure from the generated text and rejects any that is not in `facts_used`. It
runs twice: once inside `accept_refinement` after a local model rewords a draft,
and once more in `pipeline.ask` before the answer is returned. A model that
changes a figure is discarded and the deterministic template is used instead.

This is why using an LLM here is safe at all: it can make the wording warmer, it
cannot change a rupee.

A missing field is `None`, never `0`. `explain_settlement` recomputes the net
from its components and compares against the reported net; a mismatch becomes a
visible caveat, never a silent correction.

### 5.2 Highlighting without hardcoded coordinates

The server never emits pixel coordinates. It emits semantic targets
(`target_id` + `anchor_text`). The client — the only component holding a
screenshot — resolves them, best tier first:

| Tier | Source | Accuracy | Works on real Razorpay? |
|---|---|---|---|
| `dom_map` | rects the mock dashboard POSTs to `/api/merchant/screen-map` | exact | No (demo only) |
| `anchor_text` | OCR word-box search for the label text | good | **Yes** |
| `vlm` | vision model, normalised 0–1000 | rough, flagged | Yes |
| `none` | — | — | says "I can't see that" |

Every published rect is sanity-checked before use (`targeting.plausible_rect`):
zero-size, wildly negative, or outside the captured window's bounds is rejected
and the next tier is used. A browser's `window.screenX/screenY` plus a chrome
height estimate can genuinely return a negative Y; trusting it would put the
cursor off-screen. Pointing at nothing is acceptable; pointing confidently at
the wrong thing is not.

### 5.3 Read-only is structural, not a runtime check

`merchant/adapters/base.py` has no `create_*`, `refund_*` or `send_*` method.
There is nothing to call, so nothing can be bypassed. `RazorpayTestAdapter`
issues only HTTP GET and refuses any key that does not start with `rzp_test_`
(`LIVE_KEY_REFUSED`).

`merchant/confirm.py` models the promise for a hypothetical action: single-use
tokens, a 90-second TTL, duplicate approval rejected as `ALREADY_CONSUMED`, the
exact amount and a masked customer shown before approval — and
`Authorisation.executed` is always `False`, because approval is authorisation,
not execution.

## 6. Data sources

Both are read-only and selected by `merchant/adapters/get_adapter()`, defaulting
to demo. The project works with **no credentials at all**.

- **Demo** — `merchant/seed/dashboard_seed.json`, the same file the mock
  dashboard renders from. That shared source is what makes the demo honest: the
  number Clicky explains is provably the number on screen. Seven scenarios
  including empty state, simulated API failure and a settlement with missing
  fields.
- **Razorpay Test** — read-only GETs against test mode. Razorpay's settlement
  list endpoint does not expose a full gross/fees/tax breakdown, so those fields
  come back `None` with `partial=True`, and Merchant Mode says the breakdown is
  not available rather than inventing one.

## 7. Processes at runtime

```
┌─ Clicky (PyQt6, one process) ──────────────┐
│  main.py → CompanionManager                │
│    skills/merchant_mode.py  ── in-process ─┼──► merchant.pipeline
│  ui/merchant_panel.py, ui/overlay.py       │
└────────────────────────────────────────────┘

┌─ merchant.server (FastAPI, 127.0.0.1:8756) ┐
│  /api/merchant/*   ── same pipeline code ──┼──► merchant.pipeline
│  /dashboard        static mock dashboard   │
└──────────────────────┬─────────────────────┘
                       │ POST /api/merchant/screen-map every 1.5s
              ┌────────▼─────────┐
              │  mock dashboard  │  (browser)
              └──────────────────┘

Optional: Ollama on 127.0.0.1:11434 — wording only, never numbers.
```

The sidecar binds `127.0.0.1` only, never `0.0.0.0`: it can read the user's
screen, so it must not be reachable from the network.

The desktop panel and the sidecar each construct their own `MerchantPipeline`
over the same modules. The sidecar exists for the mock dashboard, the evaluation
harness and demoability without launching the full desktop app; it is not a
dependency of the desktop path.

## 8. Failure behaviour

| Situation | Behaviour |
|---|---|
| No permission | Nothing read. Asks for consent. |
| Ollama absent | Deterministic template, `fallback_used: true`. |
| Model invents an amount | Discarded, template used, audited. |
| Tesseract absent | Anchor tier unavailable; falls to dom_map/vlm/none. |
| Adapter error | "I cannot see the data", `confidence: 0.0`. No guessing. |
| Empty dashboard | "There is nothing here yet." No invented rows. |
| Missing settlement fields | Gap reported; no fake breakdown computed. |
| Page unrecognised | `page: "unknown"` — a valid answer, not an error. |
| Target not locatable | Named as not found. Nothing is pointed at. |
| Low confidence | Routed to manual verification via `uncertainty`. |
| Duplicate / expired confirmation | HTTP 409, audited as blocked. |
| Unexpected exception | Caught; answer contains no money figure. |
