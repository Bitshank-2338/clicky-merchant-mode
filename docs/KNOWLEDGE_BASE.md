# Razorpay Merchant Knowledge Base

## Overview

The Merchant Knowledge Base is a curated collection of beginner-friendly explanations of Razorpay features, designed to help shopkeepers understand payment basics without technical jargon. Every entry is:

- **Sourced from official Razorpay documentation** (razorpay.com/docs)
- **Verified with a URL and last-reviewed date**
- **Written in three languages**: English, Hindi (Devanagari), and Hinglish (Roman script)
- **Honest about unverified claims** (marked with `verified: false`)

## Schema

Each knowledge entry (matching `KnowledgeEntry` in `merchant/models.py`) contains:

| Field | Type | Purpose |
|-------|------|---------|
| `id` | string | Unique snake_case identifier |
| `topic` | string | Category: `settlements`, `payment_status`, `failed_payments`, `refunds`, `payment_links`, `fees`, `tax`, `reports`, `disputes`, `settlement_timelines` |
| `title` | string | One-line explanation headline |
| `simple_en` | string | 1–3 sentences in English, 12-year-old reading level, no jargon |
| `simple_hi` | string | Same explanation in Devanagari Hindi, equally simple |
| `simple_hinglish` | string | Same in Hinglish (Roman script), conversational |
| `source_url` | string | Official razorpay.com/docs URL from RAZORPAY_RESEARCH.md |
| `last_reviewed` | string | ISO date when source was last checked (2026-09-03) |
| `pages` | array | Relevant dashboard pages: `home`, `payments`, `settlements`, `refunds`, `payment_links`, `reports`, `disputes` |
| `keywords` | array | 5–12 search terms including Hindi/Hinglish words merchants actually use |
| `verified` | boolean | `true` if source URL confirms the fact; `false` if unverified or account-specific |

## How Entries Are Retrieved

1. **Keyword search**: Matches user query against entry `keywords` (case-insensitive)
2. **Page context**: Filters by current dashboard `page` against entry `pages`
3. **Combined**: Returns entries matching both filters, ranked by relevance

## Sourcing Rule: Official Docs Only

Every entry must cite an official razorpay.com/docs URL that was manually checked and verified. If a fact is **not** in official docs (e.g., commercial fee percentages that vary by account), the entry is marked `verified: false` and explicitly directs the merchant to check their dashboard.

## Honesty Rule: Unverified vs Verified

- **Verified (`verified: true`)**: The entry's claim is directly backed by a source URL in RAZORPAY_RESEARCH.md. Safe to show without qualification.
- **Unverified (`verified: false`)**: The claim is absent from official docs, or requires account-specific data. The entry's text explicitly acknowledges this and directs the merchant to check their own account or contact support.

Example of unverified handling:
> `fees_razorpay_charges`: "The exact percentage depends on your account type... Check your account dashboard or contact support."

## Adding a New Entry

1. Find the source URL in official razorpay.com/docs
2. Add it to `docs/RAZORPAY_RESEARCH.md` with verification status
3. Create an entry in `merchant/knowledge/kb.json`:
   - Choose a unique `id` (snake_case)
   - Pick one `topic` from the allowed list
   - Write `simple_en` (beginner language, no jargon)
   - Translate to `simple_hi` (Devanagari) and `simple_hinglish` (Roman)
   - List relevant `pages` and `keywords`
   - Set `verified: true/false` based on source status
4. Validate JSON: `python -c "import json; json.load(open('merchant/knowledge/kb.json'))"`

---

## Entry Inventory

| ID | Topic | Verified | Pages |
|----|-------|----------|-------|
| settlement_basics | settlements | ✓ | settlements, home |
| settlement_t_plus_2 | settlement_timelines | ✓ | settlements, home |
| settlement_deductions | settlements | ✓ | settlements |
| instant_settlement | settlements | ✓ | settlements |
| payment_lifecycle | payment_status | ✓ | payments, home |
| authorized_not_captured | payment_status | ✓ | payments |
| failed_payment_definition | failed_payments | ✓ | payments, home |
| money_debited_but_no_confirmation | failed_payments | ✓ | payments |
| refund_definition | refunds | ✓ | refunds, home |
| refund_full_vs_partial | refunds | ✓ | refunds |
| refund_timeline | refunds | ✓ | refunds |
| refund_vs_reversal | refunds | ✓ | refunds, payments |
| refund_fees_not_returned | refunds | ✓ | refunds |
| instant_refund | refunds | ✓ | refunds |
| payment_link_definition | payment_links | ✓ | payment_links, home |
| payment_link_required_fields | payment_links | ✓ | payment_links |
| payment_link_expiry | payment_links | ✓ | payment_links |
| payment_link_notifications | payment_links | ✓ | payment_links |
| payment_link_statuses | payment_links | ✓ | payment_links |
| fees_razorpay_charges | fees | ✗ | payments, home |
| gst_on_fees | tax | ✓ | payments, settlements |
| settlement_amount_formula | settlements | ✓ | settlements, home |
| reports_types | reports | ✓ | reports, home |
| reports_formats | reports | ✓ | reports |
| reports_scheduling | reports | ✓ | reports |
| reports_date_range | reports | ✓ | reports |
| dispute_definition | disputes | ✓ | disputes, home |
| dispute_phases | disputes | ✓ | disputes |
| dispute_statuses | disputes | ✓ | disputes |
| dispute_response_options | disputes | ✓ | disputes |
| international_settlement | settlement_timelines | ✓ | settlements |
