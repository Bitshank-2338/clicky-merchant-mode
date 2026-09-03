# Demo Results — Clicky Merchant Mode

Independent hackathon prototype. Not an official Razorpay product.

> **This prototype was evaluated on synthetic/demo data. Results do not
> represent production performance.**

Every transcript below is real output captured from a run on **2026-09-03**,
Windows 11, Python 3.11.7, **Ollama absent**, **Tesseract absent**, no Razorpay
credentials. Nothing is illustrative or rewritten.

---

## 1. Settlement shortfall — the flagship flow

**Scenario:** `settlement_lower_than_gross`
**Merchant says (Hinglish):** *"Mere payment ka settlement kam kyon aaya?"*

```
page=settlements  intent=explain_settlement  language=hinglish
confidence=0.5    requires_confirmation=False  fallback_used=True
```

> Is settlement period mein aapke customers ne ₹10,000 diye the. ₹200 fees,
> ₹36 fees par tax aur ₹500 refunds katne ke baad, aapke bank mein ₹9,264 aata
> hai. Matlab paisa aane se pehle total ₹736 kata hai.

**Highlights:** `settlement.gross_amount`, `settlement.fees`, `settlement.tax`,
`settlement.refunds`, `settlement.net_amount`
**Facts used:** 13 · **Sources cited:** 1 · **Invented numbers:** none · **PII:** none

The arithmetic is done in integer paise by `merchant/facts.py`:
`1000000 − 20000 − 3600 − 50000 + 0 = 926400` paise = **₹9,264**, which matches
the `net_amount` the dashboard reports. The same figure is rendered on the mock
dashboard from the same seed file, so the number Clicky explains is provably the
number on screen.

The identical question in **Hindi** ("मेरा सेटलमेंट कम क्यों आया?") and **English**
("Why is my settlement lower than what I collected?") returns the same figures in
the corresponding language — asserted by
`test_settlement_shortfall_in_every_language`.

## 2. Failed payments

**Scenario:** `multiple_failed_payments`
**Merchant says:** *"Kal ke failed payments dikhao"*

```
page=payments  intent=show_failed_payments  language=hinglish  steps=5
```

> Aapke 4 payment fail hue hain, total ₹5,049 ke. Reasons: 1 × account mein
> paise kam the, 1 × galat OTP daala gaya, 1 × customer ne cancel kar diya,
> 1 × bank par poora nahi hua. […]

**Warning returned:** "I cannot promise a retry will succeed — that depends on
the customer's bank."

**Guide steps produced:**

| # | Step | Target |
|---|---|---|
| 1 | Left menu mein Payments par jaayein | `nav.payments` |
| 2 | Date range choose karein | `payments.date_filter` |
| 3 | Status mein Failed select karein | `payments.status_filter` |
| 4 | Apply filters dabayein | `payments.apply_filter` |
| 5 | Failure reason column padhein | `payments.error_reason` |

`₹5,049` is the sum of the four failed amounts in the seed
(120000 + 89900 + 250000 + 45000 = 504900 paise). Saying "next" advances one
step at a time; all five complete — asserted by
`test_next_step_walks_the_checklist_and_finishes`.

## 3. Payment-link tutorial

**Scenario:** `payment_link_creation`
**Merchant says:** *"Mujhe payment link banana sikhao"*

```
page=payment_links  intent=create_payment_link_tutorial
requires_confirmation=True  steps=7
```

> Payment link ek chhota web page hai jo aap customer ko bhejte hain taaki wo
> aapko paisa de sakein. Sirf amount zaroori hai. Customer ka naam, email,
> phone sab optional […]

Seven steps covering `link.amount`, `link.description`, `link.expiry`,
`link.customer_name`, `link.customer_contact`, `link.preview` and finally
`link.create_button`, which is marked `requires_confirmation: true` and reads:

> Aap khud Create payment link dabayein — ye aakhri step aapka hai, main ye nahi
> dabaungi.

**Warning returned:** "I will walk you through the form, but I will not create
or send a link myself."

The mock dashboard's form has **no `action` attribute and no submit path**; the
Create button calls `preventDefault()` and opens a modal explaining that nothing
was created. Verified live in the browser.

## 4. Refund education

**Scenario:** `full_and_partial_refunds`
**Merchant says:** *"Customer ko refund kaise karte hain?"*

```
page=refunds  intent=refund_tutorial  requires_confirmation=True  steps=5
```

> Refund matlab jo paisa aapko mil chuka hai, wo customer ko wapas bhejna.
> Full refund = sara paisa wapas. Partial refund = aadha ya kuch hissa wapas. […]

**Warning returned:** "I never issue a refund myself. You confirm it in the
dashboard."

The answer contains none of "refund issued", "refund processed successfully",
"I have refunded" or "refund complete" — asserted by
`test_refund_education_never_claims_a_refund_happened`.

## 5. Refusing a direct instruction to act

**Merchant says:** *"Refund kar de abhi!"*

```
intent=refund_tutorial  requires_confirmation=True  confidence=0.95
```

> Main ye kaam khud nahi kar sakti. Main aapko har step dikha sakti hoon, lekin
> final button aapko hi dabana hoga — paisa aapka hai.

**Warning:** "Merchant Mode is read-only. It never moves money."
**Audit:** `action_blocked / blocked — refused to perform 'issue_refund' — read-only by design`

It still teaches: five refund steps and the relevant highlights are returned
alongside the refusal. This phrasing ("kar de" rather than "kar do") was a real
miss found during evaluation and fixed — see `docs/BUILD_LOG.md` §9.

## 6. Confirmation before a sensitive action

Captured over HTTP against the running sidecar:

```
POST /api/merchant/request-confirmation
  amount  : ₹500
  customer: A. D. · +91 ****** 2233
  expires : 90.0 s
  warning : A refund cannot be undone. The money goes back to the customer and
            the fees on the original payment are not returned to you.

POST /api/merchant/confirm-action  (approve)  -> HTTP 200
  executed: False
  note: Merchant Mode does not perform this action. Complete it yourself in the
        Razorpay dashboard — you stay in control of every rupee.

POST /api/merchant/confirm-action  (approve again) -> HTTP 409  ALREADY_CONSUMED
  "This was already confirmed once. I will not repeat it — that is how double
   refunds happen."

POST /api/merchant/confirm-action  (unknown token) -> HTTP 409  UNKNOWN_ACTION
```

The customer's real name and phone number never appear — only `A. D.` and the
last four digits.

## 7. Audit trail

```
action_blocked           blocked                 unknown confirmation token nope
action_blocked           blocked                 duplicate approval of issue_refund
confirmation_approved    approved                issue_refund: Refund order #1183 | ₹500 | A. D. · +91 ****
confirmation_requested   awaiting_confirmation   issue_refund: Refund order #1183 | ₹500 | A. D. · +91 ****
```

Every entry is masked before it is stored, then re-checked; an entry that still
contained PII would be replaced with a redaction marker rather than written.

## 8. Ollama disabled — the fallback path

**Every transcript on this page was produced with Ollama absent.** That is not a
degraded mode: the deterministic templates in `merchant/explain.py` are the
default path, and responses are honestly labelled `fallback_used: true`.

The evaluation measures this directly: **fallback success rate 100.0%** — of
every task answered without a model, all were correct on page, required content,
forbidden content, invented numbers and privacy.

The guard is tested from the other direction too. Given a model that returns:

> "Aapka settlement ₹99,999 tha aur ₹1,234 fees kati."

…the pipeline discards it, restores the verified template containing ₹9,264, sets
`fallback_used: true`, and writes an audit entry
(`test_model_that_invents_a_number_is_discarded`). A model that crashes or
returns junk falls back just as cleanly.

## 9. Edge cases

| Scenario | Merchant asks | Response |
|---|---|---|
| `empty_state` | "settlement kam kyon aaya" | "Yahan abhi kuch nahi hai, isliye samjhane ko kuch nahi hai." — **no ₹ figure of any kind**, 0 facts |
| `api_failure` | "Mere payment ka settlement kam kyon aaya?" | "Is screen par mujhe koi data nahi dikh raha, isliye main andaaza nahi lagaungi. Dashboard ne bataya: We are unable to fetch settlements right now." `confidence=0.0` |
| `incomplete_data` | "settlement kam kyon aaya" | "Is screen par kuch numbers nahi dikh rahe, isliye ye breakdown adhoora hai." Quotes gross ₹8,000 and the reported net, and warns that fees and tax are not shown. **No `computed_net` fact is produced** — it will not fabricate a breakdown from missing parts. |
| off-topic | "What is the weather in Mumbai tomorrow?" | `intent=unknown`, admits it does not know, no ₹ figure |
| no permission | any question | Asks for consent. **0 facts read.** |

The mock dashboard matches, verified live in the browser: the `incomplete_data`
settlement renders `Razorpay fees: not available` and `Tax on fees: not
available` — **not** `₹0`.

## 10. Privacy indicators

- `screenshots_stored: 0` in every `/health` and privacy snapshot — structurally
  guaranteed, since nothing in the codebase writes captured bytes to disk.
- Capture is refused until `grant-permission` is called. Verified over HTTP: an
  attempt to read settlement data beforehand — even while supplying a forged
  screen context claiming a capture had happened — returns 0 facts and no rupee
  figure. (This was a real bug found during review and fixed; see
  `docs/BUILD_LOG.md` §12.)
- `stop-monitoring` revokes capture and cloud inference immediately; the next
  question is gated again.

## Reproducing all of this

```bash
python -m pytest tests/ -q
```

```bash
python -m merchant.evaluation.runner
```

```bash
python -m merchant.server
```

Then open **http://127.0.0.1:8756/dashboard/** and follow
[docs/DEMO_SCRIPT.md](DEMO_SCRIPT.md).
