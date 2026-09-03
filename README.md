# Clicky — Merchant Mode

**A privacy-first visual and voice teacher that helps small merchants understand
and operate the Razorpay dashboard.**

Built for the Razorpay Buildathon (Open Track) on top of
[Clicky](https://github.com/Bitshank-2338/clicky-windows), an open-source
Windows desktop AI companion.

> **This is an independent hackathon prototype. It is not an official Razorpay
> product and is not affiliated with or endorsed by Razorpay.** All dashboard
> data shipped with it is synthetic.

**Looking for Clicky itself?** Merchant Mode is an additive layer — every
existing Clicky feature still works exactly as before. Clicky's own README is
preserved unchanged at **[README_CLICKY.md](README_CLICKY.md)**.

---

## The problem

A shopkeeper collects ₹10,000 through Razorpay. ₹9,264 arrives in the bank.
Nothing on the screen explains the missing ₹736 in words they use.

The same wall shows up everywhere: a payment marked *failed* with no idea
whether the customer was charged; a settlement date that hasn't arrived yet; a
refund they are afraid to click; a report their accountant asked for. These
merchants are not looking for documentation. They are looking at a dashboard,
right now, and they need someone to point at it.

## Why this is not a chatbot

A support chatbot lives in a different window and can only answer in general
terms. Merchant Mode reads the screen the merchant is already on.

| | Support chatbot | Clicky Merchant Mode |
|---|---|---|
| Knows what you are looking at | No | Yes — reads the active window |
| Uses your actual numbers | No | Yes — quotes only figures computed from your data |
| Shows you where to click | No | Yes — points the cursor at the real element |
| Waits for you and re-checks | No | Yes — step checklist, verified between steps |
| Speaks Hindi / Hinglish | Sometimes | Yes — detected automatically, selectable |
| Can it move your money | Sometimes | **Never.** Read-only by construction |

Ask *"Mere payment ka settlement kam kyon aaya?"* and it answers:

> Is settlement period mein aapke customers ne ₹10,000 diye the. ₹200 fees,
> ₹36 fees par tax aur ₹500 refunds katne ke baad, aapke bank mein ₹9,264
> aata hai. Matlab paisa aane se pehle total ₹736 kata hai.

— while highlighting the gross amount, the fee line, the tax line, the refund
line and the net settlement, one after another, on the merchant's own screen.

## Three modes

- **Learn** — *"Settlement kya hota hai?"* Explains the concept in front of you,
  sourced from official Razorpay documentation, in plain language.
- **Guide Me** — *"Failed payments kaise dekhu?"* Detects the page, highlights
  the next control, explains why the step matters, waits, re-checks, continues.
- **Explain This Screen** — *"Is screen ko simple language mein samjhao."*
  Walks through each section, the numbers on it, what you can do next, and what
  it cannot see.

## Quick start

Requires **Python 3.11+** on **Windows** (the active-window capture uses Win32
APIs). Demo Mode needs no credentials and no API keys.

```bash
pip install -r requirements.txt
```

### Run the demo (no credentials, no Ollama needed)

```bash
python -m merchant.server
```

Then open **http://127.0.0.1:8756/dashboard/** for the mock Razorpay-style
dashboard, and ask a question:

```bash
curl -s -X POST http://127.0.0.1:8756/api/merchant/grant-permission
```

```bash
curl -s -X POST http://127.0.0.1:8756/api/merchant/ask -H "Content-Type: application/json" -d "{\"utterance\":\"Mere payment ka settlement kam kyon aaya?\"}"
```

### Run the full desktop experience

```bash
python main.py
```

Merchant Mode loads as a Clicky skill. Say or type any merchant phrase
("settlement kam kyon aaya", "payment link banana sikhao", "failed payments
dikhao") and Clicky answers, highlights and speaks. Everything Clicky already
did keeps working unchanged.

### Run the tests

```bash
python -m pytest tests/ -q
```

### Run the evaluation

```bash
python -m merchant.evaluation.runner
```

## Configuration

Everything is optional. Copy `.env.example` to `.env` and edit only what you
need. See `.env.example` for the full annotated list.

| Variable | Default | Meaning |
|---|---|---|
| `MERCHANT_ADAPTER` | `demo` | `demo` or `razorpay_test` |
| `RAZORPAY_KEY_ID` | *(unset)* | Test-mode key. Must start with `rzp_test_` |
| `RAZORPAY_KEY_SECRET` | *(unset)* | Test-mode secret |
| `MERCHANT_OLLAMA_MODEL` | `llama3.2` | Local model used for **wording only** |
| `MERCHANT_AUDIT_PATH` | *(unset)* | If set, append masked audit events to this JSONL file |

**Never commit real credentials.** `.gitignore` already excludes `.env`.

### Ollama (optional)

```bash
ollama serve
```

```bash
ollama pull llama3.2
```

The sidecar detects Ollama at startup. If it is reachable, the local model is
asked to improve the *phrasing* of an answer whose numbers were already computed
deterministically; the result is re-checked and discarded if it altered any
figure. If Ollama is absent, Merchant Mode uses its deterministic templates and
labels the response `fallback_used: true`. **Both paths are supported; neither
is broken.**

### Razorpay test mode (optional)

Set `MERCHANT_ADAPTER=razorpay_test` plus the two test-mode variables. The
adapter issues **only HTTP GET**, and refuses any key that does not begin with
`rzp_test_`. Razorpay's settlement list endpoint does not expose a full
gross/fees/tax breakdown, so those fields are reported as unavailable rather
than guessed.

### Tesseract (optional, improves highlighting)

Install from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki).
It provides per-word OCR boxes, which is how Merchant Mode locates elements on
the **real** Razorpay dashboard by their label text. Without it, targeting falls
back to lower-accuracy tiers and says so.

## How screen understanding works

1. **Permission** — nothing is captured until the merchant explicitly allows it.
2. **Active window only** — one window, via `DwmGetWindowAttribute`. Never the
   whole desktop, never a second monitor.
3. **Masking** — phone numbers, emails, cards, UPI IDs, PAN, Aadhaar, IFSC, API
   keys and customer names are masked *before* the text reaches a model, a log
   or the UI. Currency figures are deliberately preserved.
4. **Page detection** — from the dashboard's own published metadata, else a URL,
   else scored OCR keywords, with an honest confidence.
5. **Facts** — every rupee figure is computed in integer paise by
   `merchant/facts.py` from adapter data.
6. **Explanation** — a deterministic template, optionally reworded by a local
   model that is forbidden from changing a number.
7. **Highlighting** — semantic targets resolved client-side through three tiers;
   if none succeeds, Clicky says it cannot see the element.

## On your real Razorpay dashboard

Merchant Mode works on the live dashboard, not only the mock — page detection
uses the real URL paths, and element targeting locates rows by their label text
via OCR.

The important part is what it does *not* do. On a live dashboard the demo
adapter is **bypassed entirely**, because its figures belong to a different
account. Amounts are read off the screen instead, and the answer says so:

> Is screen par total ₹47,320 dikh raha hai. ₹946 razorpay fees, ₹170 tax on
> fees katne ke baad ₹46,204 aapke bank jaata hai. **Ye numbers aapki screen se
> padhe gaye hain, demo data se nahi.**

If the amounts cannot be read clearly, it gives **no figure at all** rather than
falling back to demo data. This was a real bug found during review — before the
guard, it confidently quoted ₹9,264 from the seed while the screen showed
₹46,204. Covered by `tests/test_live_dashboard.py`.

## Privacy

- Screen capture is **opt-in per session** and limited to the active window.
- **No screenshot is ever written to disk.** Bytes stay in memory.
- Inference is **local by default**. Cloud inference is a separate, second
  opt-in and warns before any text leaves the machine.
- The audit trail is masked, then re-checked; an entry that still contains PII is
  withheld rather than recorded. It stays in memory unless you set a path.
- A single **Stop monitoring** button revokes capture and cloud access instantly.

Full detail in [docs/PRIVACY.md](docs/PRIVACY.md).

## Safety

- **Read-only by construction.** The adapter interface has no create, refund or
  send method — there is nothing to call.
- **No automatic refunds, links, or customer messages.** Ever.
- Asked to just do it ("refund kar de"), Merchant Mode refuses, explains why,
  and teaches the steps instead.
- Sensitive actions require a single-use confirmation that expires in 90 seconds,
  shows the exact amount and a masked customer, and cannot be redeemed twice.
- Every question, answer, refusal and approval is audited.
- It never claims a retry will succeed, and never invents a policy, amount,
  status, transaction ID or UI position.

Full detail in [docs/SAFETY.md](docs/SAFETY.md).

## What is not supported

Windows only. English, Hindi and Hinglish only. Intent and page detection are
rule-based and will miss unusual phrasing. The knowledge base is a small curated
set with a fixed review date. No production Razorpay account is ever read or
modified. Evaluation is on synthetic data only.

Read [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) before drawing any
conclusion about production behaviour.

## Documentation

| Document | Contents |
|---|---|
| [docs/PRODUCT_SCOPE.md](docs/PRODUCT_SCOPE.md) | Problem, users, modes, scope |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built and why |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Every privacy mechanism, traced to code |
| [docs/SAFETY.md](docs/SAFETY.md) | Read-only guarantees, confirmation contract |
| [docs/KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md) | KB schema, sourcing, honesty rule |
| [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md) | Measured results |
| [docs/DEMO_RESULTS.md](docs/DEMO_RESULTS.md) | Demo-flow verification |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Three-minute presenter script |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | Candid limitations |
| [docs/RAZORPAY_RESEARCH.md](docs/RAZORPAY_RESEARCH.md) | Sourced documentation digest |
| [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) | Build decisions and file ownership |
| [docs/BUILD_LOG.md](docs/BUILD_LOG.md) | What was built, in order |

## Licence and attribution

Clicky is MIT licensed (see `LICENSE`); Merchant Mode is contributed under the
same terms. "Razorpay" is a trademark of its owner and is used here only to
describe what this prototype helps merchants understand.

Every figure in the demo is synthetic. Any evaluation number shown anywhere in
this repository comes from a real run of `python -m merchant.evaluation.runner`
on that synthetic data, and does **not** represent production performance.
