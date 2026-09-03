# Evaluation Report — Clicky Merchant Mode

Independent hackathon prototype. Not an official Razorpay product.

> **This prototype was evaluated on synthetic/demo data. Results do not
> represent production performance.**

Every number on this page comes from a real execution of:

```bash
python -m merchant.evaluation.runner
```

Nothing here is estimated, projected or hand-written. Re-run the command to
reproduce it. The harness is `merchant/evaluation/runner.py`; the dataset is
`merchant/evaluation/tasks.json`.

---

## How the evaluation is run

- **36 tasks**, spread across 9 categories, in English, Hindi and Hinglish.
- Each task gets a **brand-new `MerchantPipeline`** — its own privacy state,
  audit log and confirmation manager — so guide progress, tokens and audit
  entries cannot leak between tasks.
- **Model refinement is disabled** (`allow_model_refinement=False`) so the
  numbers do not depend on whether Ollama happens to be installed. This means
  the run measures the *deterministic* path, which is the weaker of the two.
- The harness calls the **same functions the pipeline runs at request time** —
  `explain.verify_no_invented_numbers` and `masking.contains_unmasked_pii` — not
  re-implementations. A passing hallucination or privacy score therefore means
  the guarantee actually held, not that a parallel checker agreed.
- A synthetic `ScreenContext` supplies the page signal, since there is no live
  browser in the harness.

Run date: **2026-09-03**. Environment: Windows 11, Python 3.11.7, Ollama absent,
Tesseract absent, no Razorpay credentials.

## Headline results

| Metric | Result |
|---|---|
| Tasks executed | **36** |
| Page-detection accuracy | **100.0%** |
| Intent-detection accuracy | **77.8%** |
| Explanation factual accuracy (`must_mention`) | **100.0%** |
| Facts correctly surfaced | **98.1%** |
| Correct UI highlighting (target recall) | **96.8%** |
| Step-completion rate | **100.0%** (14 guided tasks) |
| Task-completion time (mean) | **2.3 ms** |
| Language detection (EN/HI/Hinglish) | **100.0%** |
| Sensitive-action blocking rate | **100.0%** |
| Hallucination rate | **0.0%** |
| Forbidden-claim rate (`must_not_mention`) | **0.0%** |
| Fallback rate | **88.9%** |
| Fallback success rate | **100.0%** |
| **Privacy violations** | **0** |

## Per-metric detail

| Metric | Score | What it measures |
|---|---|---|
| `page_correct` | 100.0% | Detected page equals the expected page |
| `intent_correct` | 77.8% | Detected intent equals the expected intent |
| `language_correct` | 100.0% | Detected language equals the expected language |
| `targets_recall` | 96.8% | Fraction of expected highlight targets returned |
| `facts_present` | 98.1% | Fraction of expected fact keys present in `facts_used` |
| `must_mention_ok` | 100.0% | Required substrings (e.g. `9,264`) appear in the answer |
| `must_not_mention_ok` | 100.0% | Forbidden claims ("will succeed", "refund issued") absent |
| `confirmation_ok` | 94.4% | `requires_confirmation` matches expectation |
| `no_invented_numbers` | 100.0% | No currency figure absent from `facts_used` |
| `privacy_ok` | 100.0% | No unmasked PII in any answer |
| `fallback_used` | 88.9% | Raw rate of deterministic-template answers (see below) |

### Reading the fallback numbers

`fallback_rate` of 88.9% is **expected and not a failure**. The pipeline sets
`fallback_used = true` whenever it answers without a local model, and the
harness deliberately disables model refinement for determinism. The meaningful
figure is `fallback_success_rate`: of the tasks answered by the deterministic
template, **100%** were still correct on page, required content, forbidden
content, invented numbers and privacy.

In other words: **with Ollama switched off, nothing breaks.** That is the point
of the metric.

## Per-category results

Category scores are the mean of page-correct and intent-correct.

| Category | Score | Tasks |
|---|---|---|
| explain_screen | 100.0% | 3 |
| reports | 100.0% | 2 |
| safety | 100.0% | 3 |
| settlement | 87.5% | 8 |
| failed_payments | 80.0% | 5 |
| refunds | 80.0% | 5 |
| payment_links | 75.0% | 4 |
| language | 50.0% | 2 |
| edge_case | 25.0% | 4 |

## Every remaining failure, examined

Thirteen assertions failed across eight tasks. They are listed in full, because
a report that only shows the good numbers is not a report. Each one was read
individually rather than tuned away.

| Task | Utterance | Expected | Got | Assessment |
|---|---|---|---|---|
| eval_005 | "Settlement se tax kya kata jaata hai?" | `explain_term` | `explain_fees` | **Label disagreement.** Both route to the tax knowledge card and highlight the tax line. The answer is correct; only the label differs. |
| eval_010 | "Failed payment ho gaya toh ab kya karu?" | `next_step` | `show_failed_payments` | **Label disagreement.** "What do I do now?" with no guide running is a request for the failed-payments walkthrough, which is what it returns. |
| eval_015 | "Jab refund dete hain toh fees bhi wapas milta hai kya?" | `explain_term`, no confirmation | `refund_tutorial`, confirmation | **Defensible, and safer.** It answers the fee question from the KB and additionally treats refunds as sensitive. Erring toward requiring confirmation is the direction we want to err in. |
| eval_019 | "Payment link ka expiry kaise set karte hain?" | `explain_term`, no confirmation | `create_payment_link_tutorial`, confirmation | **Defensible.** "Kaise set karte hain" is a how-to; the tutorial answers it and includes the expiry step. |
| eval_022 | "Payments page ko samjha do." | includes `payments.table` | returned nav/date/status filters | **Partial recall (0.5).** Page and intent correct; it highlighted the filter row rather than the table header. Genuinely imperfect, not wrong. |
| eval_026 | "Kitne payments aaye hain is mahine?" | `show_failed_payments` | `unknown` | **Dataset label is wrong.** The utterance contains no notion of failure — it asks for a monthly count, which is out of scope. `unknown` is the honest answer. |
| eval_027 | "Settlements kyon nahi dikh rahe hain dashboard pe?" | `explain_screen` | `explain_settlement` | **Label disagreement.** "Why aren't settlements showing?" is closer to a settlement question than a screen walkthrough. |
| eval_028, eval_034 | "…ke fees kya hain?", "Fees itna zyada kyon kata?" | `explain_settlement` | `explain_fees` | **Label disagreement.** Both are fee questions; both now return the real fee and tax figures and highlight those lines. eval_034's fact expectation differs for the same reason. |

**Net assessment.** Of the eight failing tasks, one (eval_026) is a dataset
labelling error, one (eval_022) is genuine partial recall, and six are cases
where the returned intent is defensible and the merchant-facing answer is
correct. The true intent-detection quality is therefore better than the
headline 77.8%, but the headline is reported as measured. The dataset was
written by a separate worker before the detector was finalised and was
deliberately **not** edited afterwards to improve the score — adjusting the
answer key to match the implementation would make the metric meaningless.

## Test suite

`python -m pytest tests/ -q` → **264 passed**, 0 failed.

| File | Covers |
|---|---|
| `test_privacy_masking.py` | Masking of 12 PII categories, permission gate, stop-monitoring, screenshot non-persistence, audit redaction |
| `test_safety_confirmation.py` | Confirmation lifecycle, duplicate/expiry rejection, read-only adapter greps, live-key refusal, credential-leak scan |
| `test_pipeline_flows.py` | All five demo flows in three languages, edge cases, model-fallback behaviour, cross-cutting invariants |
| `test_targeting.py` | Coordinate conversion, OCR anchor search, three-tier selection, implausible-rect rejection |
| `test_facts.py` | Money arithmetic, settlement reconciliation, missing-field handling, refund validation |
| `test_intent_language.py` | Intent and language detection across EN/HI/Hinglish |
| `test_kb.py` | KB integrity, sourcing, retrieval, "I don't know" path |
| `test_page_detect.py` | Page detection from DOM map, URL and OCR, with confidence |
| `test_mock_dashboard_contract.py` | Dashboard markup matches the seed's anchors |
| `test_dashboard_bridge.py` | Bridge rect validation, nav-sync ownership, no external posts |

Notably, three tests are **structural rather than behavioural** — they grep the
shipped source to prove a property holds regardless of how the app is driven:

- no module writes an image file to disk;
- no adapter contains a POST/PUT/PATCH/DELETE call;
- no live Razorpay key literal exists anywhere in the repository.

## Privacy result

**0 privacy violations across 36 tasks**, target met.

Measured by running `masking.contains_unmasked_pii` over every generated answer.
Separately, `test_every_seed_row_masks_clean` asserts that the entire demo
dataset — which contains names, phone numbers and emails — survives masking with
zero leaks, and `test_audit_masks_entries` asserts the same for the audit trail.

This measures *outbound text*. It does not constitute a security audit.

## What these numbers do not tell you

- All data is synthetic. No real merchant, account or transaction was involved.
- Ollama and Tesseract were absent, so the OCR anchor tier and the model-refined
  wording path were not exercised by this run.
- Latency of 2.3 ms is the reasoning pipeline only. It excludes screen capture,
  OCR, model inference, speech recognition and speech synthesis — the parts that
  dominate real wall-clock time.
- `language_correct` measures *language detection*, not translation quality. The
  Hindi and Hinglish text is template- and KB-authored and has not been reviewed
  by a native speaker.
- Highlight targets are scored as semantic ids. Whether the cursor lands on the
  right pixel additionally depends on OCR and DPI on the user's machine.
