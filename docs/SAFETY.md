# Clicky Merchant Mode — Safety Design

This is an independent hackathon prototype, not an official Razorpay product.

Merchant Mode is read-only by design, confirmed before any sensitive action, and guaranteed never to invent financial figures. This document explains the mechanisms.

## Read-Only by Design

The safety guarantee is structural, not a runtime check. The adapter interface (`merchant/adapters/base.py`) declares only read methods — there is no `create_*`, `refund_*`, `settle_*`, or `modify_*` method anywhere in the public interface, and none should ever be added.

**What the adapter can do**:
- `settlements(limit) -> DataResult` — read settlements.
- `payments(limit, status) -> DataResult` — read payments.
- `refunds(limit) -> DataResult` — read refunds.
- `payment_links(limit) -> DataResult` — read payment links.
- `failed_payments(limit) -> DataResult` — convenience view of failed payments.
- `health() -> bool` — check if the adapter is reachable.

**What it cannot do**:
- Issue refunds.
- Create payment links.
- Cancel or retry payments.
- Settle immediately.
- Message customers.
- Modify account settings.
- Delete anything.

Both adapters (demo and Razorpay test) inherit this contract and add no mutating methods. A code audit would find zero POST/PUT/PATCH/DELETE HTTP operations in `merchant/adapters/razorpay_test.py` — only GET requests.

## Live-Key Refusal

The Razorpay Test Mode adapter refuses to operate if a live key is configured, even if the merchant sets it.

**How it works** (`merchant/adapters/razorpay_test.py`, lines 77–95):
- `_is_test_key(key_id)` checks whether the key starts with `rzp_test_`.
- `_refuse_reason()` returns a refusal code and message if:
  - The key is missing or malformed.
  - The key starts with `rzp_live_` (or any non-test prefix).
- Every public read method (`_get()` on line 111) calls `_refuse_reason()` first.
- If a live key is detected, the response is `LIVE_KEY_REFUSED`: *"Merchant Mode only ever talks to Razorpay TEST mode. The configured RAZORPAY_KEY_ID does not look like a test key (it must start with 'rzp_test_')."*

**Secrets never appear in error messages**. The refusal message never quotes or hints at the actual key value — only the prefix is checked.

## Confirmation Contract

If Merchant Mode ever reaches a point where it would touch money (a hypothetical future feature), a confirmation gate would apply. This is modelled now so the pattern is auditable.

**The contract** (`merchant/confirm.py`):
- Every sensitive action gets a `ConfirmationRequest` with:
  - The action kind (e.g., `issue_refund`, `create_payment_link`).
  - The exact amount in rupees, e.g., *"₹500"*.
  - The masked customer: initials + last-4 phone, e.g., *"R. V. · +91 ****** 5678"*.
  - A warning specific to the action.
  - A 90-second expiry timer.

**Single-use tokens** (line 112):
- Every confirmation request gets a unique 16-character hex token.
- Tokens are tracked in `_pending: dict[action_id, PendingAction]`.
- Once redeemed by `approve(action_id)`, the `consumed` flag is set to `True`.

**Duplicate-approval prevention** (lines 165–172):
- If the merchant tries to approve the same token twice, `ALREADY_CONSUMED` error is raised.
- The audit log records the duplicate attempt as `KIND_ACTION_BLOCKED`.
- This prevents double-refunds from accidental double-clicks.

**TTL expiry** (default 90 seconds, line 39):
- Tokens expire automatically (line 174: `pending.is_expired(t)`).
- An expired token raises `EXPIRED` error: *"That confirmation timed out. Please start again so you can check the amount fresh."*
- The merchant must re-ask, see the amount again, and re-confirm.

**Authorisation, not execution** (lines 76–87):
- Confirming a token returns an `Authorisation` object, not an execution result.
- `Authorisation.executed` is always `False`.
- The execution note is hardcoded: *"Merchant Mode does not perform this action. Complete it yourself in the Razorpay dashboard — you stay in control of every rupee."*
- In a live system, the merchant would click a button in the dashboard to actually execute.

## Actions That Are Never Automated

Certain actions are explicitly in the `NEVER_AUTOMATED` set (`merchant/confirm.py`, lines 43–50). Asking Clicky to just "do it" for these produces a teaching response, not a confirmation flow.

**The set**:
- `issue_refund` — money goes back to the customer.
- `send_payment_link` — a real customer receives it immediately.
- `create_payment_link` — commits a payment flow.
- `message_customer` — direct contact with a customer.
- `cancel_payment` — reverses a transaction.
- `settle_now` — instant settlement (unusual and expensive).

**The refusal flow** (`merchant/pipeline.py`, lines 59–69 + line 185):
- `_detect_action_demand(utterance)` matches phrases like *"refund kar do"*, *"link bhej do"*, *"settle karo"*.
- If detected, `_refuse_action()` is called before anything else.
- The response is `blocked_action_message()` in the merchant's language (lines 273–282):
  - **English**: *"I will not do this for you. I can show you every step, but the final button has to be yours — it is your money."*
  - **Hinglish**: *"Main ye kaam khud nahi kar sakti. Main aapko har step dikha sakti hoon, lekin final button aapko hi dabana hoga — paisa aapka hai."*
- The pipeline then offers a "Guide Me" tutorial instead.

## Anti-Hallucination Guarantee

Every rupee figure Merchant Mode quotes is computed by `merchant/facts.py` arithmetic from dashboard data. The LLM cannot invent numbers.

**Fact extraction** (`merchant/facts.py`):
- `explain_settlement(row)` computes the settlement math: `net = gross − fees − tax − refunds + adjustments − disputes`.
- Every component is read from the data source and wrapped in a `Fact` object (with `value_text`, `source`, `raw_value`).
- Missing fields are explicitly marked as `None`, not guessed as `0`.
- The computed net is compared against the reported net; a mismatch is flagged as a warning, never silently corrected.

**Guard on generated text** (`merchant/explain.py`, lines 57–86):
- `verify_no_invented_numbers(answer, facts)` extracts every currency figure from the LLM's response.
- It checks whether each figure appears in the fact list (after normalisation).
- `_canon()` removes currency symbols and spacing: `"₹9,264"` → `"9264"` so formatting differences don't cause false negatives.
- If any currency amount is not in the facts, the list of invented figures is returned.
- `strip_to_safe(answer, template, facts)` discards an answer that invents money and returns the deterministic template instead.
- This is enforced at runtime in the pipeline and tested in the evaluation suite.

## Honest-Uncertainty Rules

Merchant Mode refuses to guess when it cannot see or resolve something.

**Missing fields become `None`, not `0`** (`merchant/facts.py`, lines 96–104):
- If a settlement row omits `fees`, `tax`, or `refunds`, those components are recorded as `None` in the breakdown.
- The missing fields are listed in `missing: []`.
- A warning is appended: *"This settlement does not show fees, so I cannot work out the full breakdown."*
- The merchant is told what information is unavailable, not given a fake total.

**Unresolvable highlights are reported** (`merchant/targeting.py`):
- If OCR, DOM map, and VLM all fail to locate an anchor target, the result is `ResolvedTarget(found=False)`.
- The merchant is told: *"I could not read that from your screen."*
- No guess is presented as fact.

**Low-confidence detections are surfaced** (`merchant/models.py` + `merchant/page_detect.py`):
- Page detection returns a `DashboardPage` enum and a confidence score.
- If confidence is below `LOW_CONFIDENCE_THRESHOLD`, the page is treated as `UNKNOWN` and the merchant is asked rather than the pipeline asserting.
- Intent detection likewise weights patterns; a weak match returns `Intent.UNKNOWN`.

## Language on Failed Payments

Failed payments are handled honestly. Clicky never promises that a retry will succeed.

**The caution** (`merchant/explain.py`, `_EN`, lines 119–121):
> A failed payment means the money never reached you. If the customer was debited, banks usually return it on their own. Asking them to try again may work, but nobody can promise it will.

**In Hindi** (`_HI`, lines 141–143):
> फेल पेमेंट का मतलब है पैसा आप तक पहुँचा ही नहीं। अगर ग्राहक के खाते से कट गया था, तो बैंक आमतौर पर खुद वापस कर देता है। दोबारा कोशिश करने को कह सकते हैं, पर यह पक्का नहीं कहा जा सकता कि सफल होगा।

This avoids the false comfort of "just ask the customer to retry" without acknowledging uncertainty.

## Post-Generation Re-Check

After an optional model refinement step, the pipeline re-checks the answer before presenting it to the merchant.

**How it works** (`merchant/pipeline.py` + `merchant/explain.py`):
- The deterministic template is generated first.
- If Ollama is available and `allow_model_refinement=True`, the template + facts are sent to Ollama for phrasing improvement.
- The result is checked: `strip_to_safe(answer, template, facts)`.
- If the refined answer invents numbers or violates other constraints, the original template is used.
- The merchant always gets an honest answer, never a speculative one.

