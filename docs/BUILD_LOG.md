# Build Log — Clicky Merchant Mode

Independent hackathon prototype. Not an official Razorpay product.

A record of what was built, in order, and what went wrong along the way. Bugs
are listed because they are the honest part of the story — several were found
only by running the thing, and one was a real privacy hole.

---

## Phase 1 — Inspection (Opus supervisor)

1. Cloned `github.com/Bitshank-2338/clicky-windows` @ `cdbc8ee` into the working
   directory, preserving git history so `git diff` shows exactly what was added.
2. Discovered the brief's architecture description was wrong: Clicky is **PyQt6,
   single process**, with no Electron, no sidecar and no FastAPI. Recorded the
   correction in `docs/AGENT_HANDOFF.md` and redesigned around the real code.
3. Found the real extension point: `skills/__init__.py`, a trigger-regex plugin
   system evaluated *before* the LLM. This is what makes Merchant Mode purely
   additive.
4. Defined the typed contracts first (`merchant/models.py`) and the shared seed
   dataset (`merchant/seed/dashboard_seed.json`) so parallel workers could not
   drift apart.

## Phase 2 — Delegated construction

Workers were given exclusive file ownership and narrow briefs. Ownership is
tabulated in `docs/AGENT_HANDOFF.md`.

| Task | Model | Output |
|---|---|---|
| Clicky repository audit (read-only) | Haiku | API inventory of 12 modules |
| Razorpay documentation research | Haiku | `docs/RAZORPAY_RESEARCH.md` |
| Mock Razorpay-style dashboard | Haiku | `mockdashboard/*` (~1350 lines, no build step) |
| Knowledge base + docs | Haiku | `merchant/knowledge/kb.json` (31 entries), `docs/KNOWLEDGE_BASE.md` |
| Evaluation dataset | Haiku | `merchant/evaluation/tasks.json` (36 tasks) |
| Domain unit tests | Haiku | 5 test files, 118 tests |
| Documentation drafts | Haiku | scope, privacy, safety, demo script, limitations |
| Razorpay test adapter | Sonnet | `merchant/adapters/razorpay_test.py` |
| FastAPI sidecar + eval runner | Sonnet | `merchant/server.py`, `merchant/evaluation/runner.py` |
| PyQt panel + Clicky skill | Sonnet | `ui/merchant_panel.py`, `skills/merchant_mode.py` |

Written by the supervisor directly, because they are the parts where a mistake
is a safety or privacy failure rather than a bug: `models.py`, `masking.py`,
`privacy.py`, `audit.py`, `confirm.py`, `facts.py`, `explain.py`, `kb.py`,
`intent.py`, `page_detect.py`, `ocr_boxes.py`, `targeting.py`, `pipeline.py`,
the `screen/capture.py` addition, and the privacy/safety/pipeline/targeting
test suites.

## Phase 3 — Bugs found and fixed

### Found by tests

1. **Phone numbers with internal spaces were not masked.**
   `+91 98123 45678` slipped through a regex that required ten contiguous
   digits. Rewritten to allow separators between digits, while deliberately
   excluding the comma so `₹9,264` is not eaten as a phone number.
   *Caught by `test_masking_leaves_no_recognisable_pii[phone]`.*

2. **`kb.kb_answer` did not exist.**
   `pipeline._payment_link` and `_refund` called `kb.kb_answer`; the function
   lives in `explain`. The pipeline's own exception handler swallowed the
   `AttributeError`, so every refund and payment-link tutorial silently
   degraded to "I don't understand" — with `requires_confirmation` left
   `False`. Found independently by a test and by the sidecar worker.

3. **A handler's deliberate confidence was overwritten.**
   An adapter failure sets `confidence = 0.0`, but the generic formula then
   recomputed it to `0.857`. Replaced with a `-1.0` sentinel so a handler that
   knows better is never second-guessed.

4. **A bare "What is …" claimed a term explanation for anything.**
   "What is the weather in Mumbai tomorrow?" was classified `explain_term`.
   `EXPLAIN_TERM` now requires a recognised merchant topic, otherwise the
   answer is honestly `unknown`.

### Found by running the evaluation

5. **"the" was listed as a Hinglish marker word.** English sentences
   containing "the" were classified Hinglish. Language accuracy 91.7% → 100%.

6. **Definitional questions lost to topic rules.** "Settlement period kya hota
   hai?" became a settlement walkthrough instead of a definition. Added a
   higher-weighted definitional pattern, gated on a topic hint being present.

7. **"Payments page ko samjha do" was not recognised.** The explain-screen
   pattern required a leading demonstrative ("is"/"this"/"ye"). Made optional
   and re-weighted above topic rules. Explain-screen category 33% → 100%.

8. **"Ye payment kyon fail hua?" missed.** The pattern only handled the
   question word *after* the verb.

9. **A safety miss: "refund kar de" was not caught as an action demand.**
   The detector used a fixed substring list containing "refund kar do" but not
   "kar de", "kardo" or "kar dijiye" — so a direct instruction to issue a
   refund was treated as an ordinary question. Replaced with imperative
   patterns. Safety category 66.7% → 100%.

10. **Knowledge answers pointed at nothing.** Fee, tax, report and term
    questions returned a knowledge-base card with no facts and no highlight
    targets — i.e. a chatbot answer. They now attach the real figure from the
    merchant's data and highlight the row it is on. This was the largest single
    quality gain: `targets_recall` 60.2% → 96.8%, `facts_present` 86.1% → 98.1%.

11. **Topic-hint ordering resolved specific questions to the broad topic.**
    "Settlement se tax kya kata jaata hai?" matched `settlements` before `tax`,
    so Clicky highlighted the UTR instead of the tax line. Reordered
    specific-before-broad.

### Found by driving the real system

12. **A privacy hole: the permission gate could be bypassed.**
    The gate passed when `screen.captured` was true, on the theory that a
    caller holding a screenshot must already have consent. But `captured` is
    caller-supplied — an HTTP client could set it and read account data with no
    permission at all. Verified live: the sidecar returned a full settlement
    breakdown with 13 facts before permission was granted. Consent is now read
    from exactly one place, `PrivacyState`, and nothing a caller says
    substitutes for it. Regression test added.

13. **The DOM bridge published negative screen coordinates.**
    Driving the mock dashboard in a browser showed rects at `y = -523` for
    elements plainly on screen: `outerHeight - innerHeight` is only an estimate
    of browser chrome and goes wrong when the page is embedded or zoomed.
    Clicky would have pointed off-screen. Fixed on both sides — the dashboard
    omits implausible rects rather than sending them, and
    `targeting.plausible_rect` validates every rect against the captured
    window's bounds before trusting it.

14. **The dashboard's sidebar highlight drifted from the page.**
    First load and every scenario switch highlighted "Home" while rendering
    Settlements. Nav highlighting moved into `renderPage` so the two cannot
    disagree.

15. **Failure reasons stayed English inside Hinglish answers.**
    "1 × not enough balance" in an otherwise Hinglish sentence. Localised into
    Hindi and Hinglish.

## Phase 4 — Supervisor review

- Verified the read-only claim by grepping the adapters for write verbs, as a
  test rather than by inspection (`test_adapters_contain_no_write_calls`).
- Verified the live-key refusal and that no secret appears in any error string.
- Verified the confirmation lifecycle over HTTP: single-use, duplicate rejected
  409 `ALREADY_CONSUMED`, unknown token rejected, all audited with the customer
  masked.
- Verified Clicky is intact: `skills.load_all()` still loads the pre-existing
  Self Mode skill, `capture_all_screens()` still works, and the merchant
  trigger does not shadow `tutor.NEXT_RE`'s ownership of "next"/"continue".
- Verified the mock dashboard renders the seed correctly and publishes all nine
  settlement targets plus navigation.
- Re-ran the full test suite and the evaluation after every fix.

## Notes on delegation

Model routing was available and used. Three workers ran concurrently at most.
No worker spawned a worker, and no two workers held the same file.

Two worker reports needed correcting rather than accepting:

- The sidecar worker reported `intent_correct 52.8%` and diagnosed a pipeline
  bug as the cause. The diagnosis was right, the numbers were stale — the fix
  had already landed — so the evaluation was re-run rather than the figures
  reused.
- One worker's report claimed all its verifications matched. They did, but the
  claims were re-run by the supervisor rather than taken on trust; that is how
  the "next"-shadowing gap and the negative-coordinate bug surfaced.
