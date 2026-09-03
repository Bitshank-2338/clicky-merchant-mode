# Clicky Merchant Mode — Product Scope

This is an independent hackathon prototype, not an official Razorpay product.

## The Problem

Small merchants using Razorpay are confused by settlements. They receive ₹10,000 in payments but ₹9,264 lands in their bank account. They see red "failed" payment rows and don't know why or what to do. They want to issue a refund or create a payment link but the dashboard's forms are intimidating. No single page explains the math. No assistant speaks their language — not Hindi, not the Hinglish they actually use.

Clicky Merchant Mode is a read-only guide that sits alongside the Razorpay dashboard, reads the screen the merchant is already on, points at the actual pixels, explains in English or Hinglish, and refuses to move money.

## Target Users

- **Micro-merchants**: single-location shops, individual service providers, freelancers.
- **Non-technical**: comfortable on WhatsApp, not comfortable with financial jargon or English-only dashboards.
- **Pragmatic**: they trust their own eyes more than a chatbot. They want to see what changed on their screen, not a summary from an AI.

## Three Core Modes

Merchant Mode speaks in three ways:

### 1. "Learn" Mode — Explain This Screen

Merchant says: **"Mere settlement mein paisa kam kyon aaaya?"** (Why is my settlement short?)

Clicky reads the settlements page, extracts the exact row, computes the math, and explains:
- **Gross collected**: ₹10,000
- **Razorpay fees**: ₹200
- **Tax on fees**: ₹36
- **Refunds issued**: ₹500
- **Net reached**: ₹9,264

It points at each number on the screen with an arrow and explains the settlement identity: `net = gross − fees − tax − refunds`. (Data from `merchant/seed/dashboard_seed.json`, scenario `settlement_lower_than_gross`.)

### 2. "Guide Me" Mode — Step-by-Step Form Guidance

Merchant says: **"Mujhe payment link banana sikhao"** (Teach me to make a payment link.)

Clicky detects the intent (`merchant/intent.py`), recognises the page (`merchant/page_detect.py`), and walks through the form field by field:
1. "Fill in the amount the customer will pay"
2. "Write a short description — what is this for?"
3. "(Optional) When should this link expire?"
4. "(Optional) Who is this for?"

Each step is accompanied by highlighting on the actual form. The merchant stays in control and clicks every button themselves.

### 3. "Explain This Term" Mode — Knowledge Lookup

Merchant says: **"UTR kya hota hai?"** (What is a UTR?)

Clicky queries its knowledge base (`merchant/knowledge/kb.json`) and explains in the merchant's language. Definitions are curated, not AI-generated, so they are accurate and concise.

## Why This Is Not a Chatbot

Clicky is fundamentally different from a chatbot. It:

- **Reads the screen the merchant is already on** — not a separate chat window. It captures the active window (`screen/capture.py`: `capture_active_window`), never the whole desktop or a second monitor.

- **Points at actual pixels** — not summaries. When it says "your settlement", it highlights the exact row on the dashboard. The merchant confirms with their eyes (`merchant/targeting.py`: three-tier resolution using DOM map, anchor text OCR, and vision-model fallback).

- **Refuses to act** — explicitly. If a merchant says "refund kar do" (just do the refund for me), Clicky says no and shows them how to do it themselves. Read-only by design (`merchant/adapters/base.py`: no `create_*` or `refund_*` methods exist).

- **Never invents numbers**. Every rupee figure comes from `merchant/facts.py` arithmetic over dashboard data. The LLM can only rephrase, not calculate (`merchant/explain.py`: `verify_no_invented_numbers` rejects any answer that quotes a currency value not in the fact list).

- **Stays honest about what it cannot see** — `merchant/page_detect.py` returns confidence alongside every page detection; low-confidence guesses are reported, not silently acted on.

## Scope — In and Out

### In Scope

- Read the active window only (Razorpay dashboard, mock dashboard during demo).
- Explain settlements, failed payments, refunds, and payment links using facts extracted from the displayed data.
- Guide merchants through form-filling (amounts, customer details, descriptions).
- Answer common questions about Razorpay terms and payment mechanics.
- Operate in English, Hindi (Devanagari), and Hinglish (Roman-script Hindi).
- Audit every action the merchant takes (questions asked, data read, explanations given, actions refused).
- Masking and local-first inference by default; optional cloud inference with explicit warning.

### Out of Scope

- Modifying, creating, or refunding anything (`NEVER_AUTOMATED` in `merchant/confirm.py`).
- Reading anything except the active window.
- Storing screenshots or raw customer data to disk.
- Operating on browsers other than the mock dashboard or real Razorpay dashboards.
- Providing financial advice or investment recommendations.
- Handling disputes, chargebacks, or complex settlement issues beyond explanation.
- Integrating with Razorpay's Chat or Email APIs.

## Data Modes

Merchant Mode can run in two data modes:

### Demo Mode (Synthesis Data)

- Merchant runs Clicky locally with no API credentials.
- All data is seeded from `merchant/seed/dashboard_seed.json` — the mock dashboard and Clicky see the same numbers.
- Every explanation is reproducible and matches the displayed data exactly.
- Used for demos, evaluation, and testing without touching a real account.

### Razorpay Test Mode (Read-Only)

- Merchant configures `RAZORPAY_KEY_ID` (must start with `rzp_test_`) and `RAZORPAY_KEY_SECRET`.
- Clicky reads the merchant's actual test-mode account data via the Razorpay API.
- Read-only enforced structurally: the adapter issues only GET requests (`merchant/adapters/razorpay_test.py`).
- Live keys (`rzp_live_`) are refused immediately (`LIVE_KEY_REFUSED` in the adapter).
- Settlement breakdowns are incomplete because Razorpay's list endpoint omits the fee/tax/refund fields — Clicky reports this gap rather than guessing.

## Capabilities by Adapter Mode

| Feature | Demo | Razorpay Test |
|---------|------|-------|
| Settlement breakdown | Complete (all fields) | Incomplete (no breakdown fields) |
| Real data | Synthetic seeded data | Merchant's actual test account |
| Data freshness | Static across session | Live API calls |
| Setup required | None | RAZORPAY_KEY_ID + KEY_SECRET |
| Safety | Read-only (inherent) | Read-only (test key + no mutating methods) |

