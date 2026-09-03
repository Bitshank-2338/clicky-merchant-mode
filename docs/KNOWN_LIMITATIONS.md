# Clicky Merchant Mode — Known Limitations

This is an independent hackathon prototype, not an official Razorpay product.

Merchant Mode works well within its scope but has real limitations. This document is honest about them.

## Platform Limitations

**Windows-only active-window capture**
- Active-window capture uses `ctypes.windll` and Windows-specific APIs (DwmGetWindowAttribute).
- It does not run on macOS, Linux, or other platforms.
- The existing Clicky feature (full-screen capture) works on other platforms; Merchant Mode's active-window guarantee is Windows-only.
- Fallback: on non-Windows systems, Merchant Mode would need to adapt or be disabled.

## OCR Limitations

**Requires Tesseract**
- Word-box OCR (finding exact positions of text on screen) uses Tesseract via the `tutor_features/ocr.py` module.
- If Tesseract is not installed, the targeting system falls back from anchor-text matching to vision-model fallback, which is less precise.
- The anchor-text tier becomes unreliable (it skips phrases that cannot be found with confidence).

**Limitations of OCR itself**
- OCR misses text rendered as images (e.g., screenshots or custom fonts).
- OCR struggles with overlapping UI elements, rotated text, or very small text.
- Spacing artifacts ("₹9 , 264" instead of "₹9,264") can prevent exact matching.

## Detection Limitations

**Intent and page detection are rule-based, not model-based**
- Intent detection (`merchant/intent.py`) uses regex patterns, not a classifier.
- It works for the phrases in the codebase but will miss novel phrasing or typos.
- Example: "Why is my settlement short?" matches. "Why did the money I was supposed to get fall short?" might not.
- Page detection (`merchant/page_detect.py`) scores keyword evidence and returns confidence; low-confidence pages are reported as unknown rather than guessed.

**The knowledge base is fixed and curated**
- `merchant/knowledge/kb.json` is a small, hand-written set of definitions.
- It was reviewed and frozen at a point in time (last-reviewed date in the source).
- New Razorpay features, policy changes, or product updates are not automatically reflected.
- Stale information is a real risk for a guide that claims to teach.

## Data Adapter Limitations

**Razorpay Test Mode returns incomplete settlement data**
- The Razorpay API endpoint `GET /settlements` returns id, status, created_at, and net_amount, but not the breakdown fields (gross, fees, tax, refunds, adjustments, disputes).
- Merchant Mode detects this in `merchant/adapters/razorpay_test.py` (lines 40–47) and reports the missing fields explicitly, but cannot compute the full breakdown.
- Demo Mode (seeded data) has the complete breakdown and works perfectly; Razorpay Test Mode degrades gracefully by reporting the gap.

**No live-account settlement detail endpoint**
- Razorpay's public API does not expose a settlement-detail endpoint that includes the full breakdown.
- This is a Razorpay API limitation, not a Clicky limitation, but it means real-account users cannot get full explanations via the Test Mode adapter.

## Highlighting Limitations

**Mock dashboard coordinate mapping is approximate**
- The mock dashboard publishes screen coordinates via `window.screenX`-based calculation.
- On some DPI scales or browser zoom levels, the mapping can be off by a few pixels.
- In production (real Razorpay dashboard), there is no equivalent mechanism; highlighting falls back to OCR or vision-model resolution, both of which are less precise.

**Vision-model fallback is normalized, not exact**
- When anchor-text and DOM-map fail, the vision model is asked for "normalised 0–1000 coordinates".
- These are then mapped to logical screen space.
- Normalisation can cause rounding errors; exact pixel positioning is not guaranteed.

## Language Limitations

**Hindi/Hinglish output is template-driven**
- Explanations are phrased from templates (defined in `merchant/explain.py`).
- Templates are hand-written and cover the main flows but are not exhaustive.
- Natural, idiomatic Hindi/Hinglish for *every* explanation is not generated; uncommon scenarios may get English-like templated text.
- A native Hindi reviewer should audit the templates before production use.

**Language detection is rule-based**
- `merchant/intent.py` detects language via Devanagari characters and Hinglish keyword matching.
- Code-mixed or unusual phrasing may be misclassified.
- Once misclassified, the merchant gets an explanation in the wrong language.

## Integration Limitations

**Merchant Mode only works with Razorpay (or the mock dashboard)**
- It is hard-coded to recognize Razorpay dashboard pages and Razorpay settlement/payment structures.
- It cannot reason about other payment platforms.
- Porting to another platform would require new page detection, new adapters, and new knowledge base.

**No real-account end-to-end flow**
- Confirmation tokens are modelled but never executed against a real Razorpay account.
- The pipeline has been tested against demo data and is structurally sound, but refund/create-link/settle flows have *not* been proven against a production account.
- The confirmation gate would need real-world validation before a merchant's money is actually at stake.

## Evaluation Limitations

**All evaluation is on synthetic data**
- The mock dashboard and seeded data are carefully crafted to match the intended scenarios.
- Real merchant dashboards are messier: incomplete fields, unusual formatting, rare edge cases.
- Metrics (success rate, confidence, latency) measured on synthetic data do not transfer directly to production.

**No real-user testing**
- Merchant Mode has not been tested with actual small merchants.
- Assumed phrasing ("paisa kam kyon aaya") may not match real speech patterns.
- Intent and page detection may fail on real utterances or real dashboard variations.

**Evaluation harness is not representative**
- `merchant/evaluation/tasks.json` defines evaluation scenarios, but scenarios are authored by the team.
- They do not reflect the distribution of real merchant questions.
- A true evaluation would require logging real sessions and mining actual questions.

## Not Supported

These capabilities are explicitly out of scope:

- **Modifying or creating anything** — read-only by design.
- **Handling multi-currency** — hardcoded to INR.
- **Handling multi-language output beyond English/Hindi/Hinglish** — templates for other languages are not included.
- **Operating outside the active window** — Merchant Mode will not read the desktop, other applications, or second monitors.
- **Retrying or recovering from transient errors** — network failures are reported, not automatically retried.
- **Persisting state across sessions** — every session starts fresh; no saved preferences.
- **Integrating with Razorpay Chat, Email, or SMS APIs** — those channels are out of scope.
- **Handling disputes or chargebacks** — complex settlement issues are outside the knowledge base.
- **Providing tax or accounting advice** — Merchant Mode explains the numbers, not tax implications.
- **Customizing the UI for individual merchants** — the panel and overlay are fixed.

## What We Would Do Next

If this were production:

1. **Native language review** — Have the Hindi/Hinglish templates reviewed by native speakers and actual merchants.

2. **Real-world detection tuning** — Collect logs from real merchants and retrain intent/page detection on actual phrasing and dashboard variations.

3. **Razorpay settlement API enhancement** — Advocate for a settlement-detail endpoint that includes the full breakdown, so Test Mode can provide complete explanations.

4. **End-to-end action validation** — Execute confirmation flows (refunds, payment-link creation) against a test account to verify the UX and the audit trail.

5. **Persistent audit storage** — Add encrypted, merchant-owned audit log storage (e.g., Supabase with RLS) so merchants can export their history.

6. **Multi-platform active-window capture** — Implement macOS and Linux equivalents using platform-specific window APIs.

7. **Offline knowledge base** — Build a versioned, downloadable knowledge base so merchants can reference definitions without an internet connection.

8. **Accessibility audit** — Ensure the overlay, highlighting, and color contrasts meet WCAG 2.1 AA standards for merchants with visual impairments.

9. **Merchant feedback loop** — In-app thumbs-up/thumbs-down on explanations, linked to the audit trail, to identify where the system is failing.

10. **Multilingual expansion** — Add Gujarati, Marathi, Telugu, Tamil, Kannada, and other regional languages with native review.

