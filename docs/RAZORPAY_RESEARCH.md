# Razorpay Official Documentation Research Digest
**Checked: 2026-09-03** | All facts sourced from razorpay.com/docs

---

## 1. Settlements

**Fact:** A settlement is the process where money received from customers is settled (credited) to a merchant's bank account after Razorpay deducts fees.
- Source: https://razorpay.com/docs/payments/settlements/faqs/ (checked 2026-09-03)

**Simple explanation:** Razorpay collects money from customers and sends it to your bank account, but takes out their service fees first.

**Hinglish explanation:** Razorpay apke customers se paise leta hai, apna fee nikaal kar baki paise aapke bank account mein bhej deta hai.

**Fact:** Standard settlement cycle for domestic payments is T+2 working days (where T = capture date). Working days exclude weekends and bank holidays.
- Source: https://razorpay.com/docs/payments/settlements/faqs/ (checked 2026-09-03)

**Simple explanation:** Your payment settles within 2 business days after being captured, not counting weekends or holidays.

**Hinglish explanation:** Aapka payment 2 business days mein settle ho jata hai capture hone ke baad, weekends aur holidays nahi count hote.

**Fact:** Settlement deductions include: fees (charged by Razorpay), taxes (GST at 18% on fees, except domestic card payments ≤₹2,000), refunds, adjustments, and disputes.
- Source: https://razorpay.com/docs/payments/settlements/faqs/ (checked 2026-09-03)

**Simple explanation:** Razorpay subtracts fees, taxes, refunded amounts, and disputed chargebacks from your settlement.

**Hinglish explanation:** Settlement mein se Razorpay apna fee, tax, refund kiye hue paise aur disputes nikaal deta hai.

**Fact:** On-demand (Instant) Settlements allow withdrawal 24/7 for a small fee (T+0 cycle, minutes via IMPS up to ₹5L, or up to 1 hour via RTGS for larger amounts). Feature requires activation by contacting support.
- Source: https://razorpay.com/docs/payments/settlements/instant/ (checked 2026-09-03)

**Simple explanation:** You can get your money instantly anytime for a small fee instead of waiting T+2 days.

**Hinglish explanation:** Tum apne paise kisi bhi waqt instant nikaal sakte ho chhote fee ke liye, T+2 din intezaar karne ki zaroorat nahi.

---

## 2. Payment Status Lifecycle

**Fact:** Payments progress through states: created → authorized → captured → settled (or failed/refunded). Captured payments settle automatically; authorized but not captured payments auto-refund in 5 days.
- Source: https://razorpay.com/docs/payments/payments/faqs/ (checked 2026-09-03)

**Simple explanation:** Payments start as created, get authorized, then captured (final), then settle to your account. If not captured after 5 days, the customer's money returns to them.

**Hinglish explanation:** Payment first create hota hai, fir authorized, fir captured, phir settle ho jata hai. Agar 5 din mein capture nahi hua to paise customer ko wapas chale jate hain.

**Fact:** Webhook events exist for `payment.authorized`, `payment.captured`, and `payment.failed` to notify merchants of status changes.
- Source: https://razorpay.com/docs/payments/payments/dashboard/ (checked 2026-09-03)

**Simple explanation:** Razorpay sends you notifications when a payment is authorized, captured, or fails.

**Hinglish explanation:** Razorpay aapko message bhejta hai jab payment authorize, capture, ya fail ho jata hai.

---

## 3. Failed Payments

**Fact:** Failed payment error codes are categorized by source: customer errors (wrong OTP, invalid card), business errors (merchant config issues), gateway errors (bank/PSP downtime), and Razorpay errors.
- Source: https://razorpay.com/docs/errors/payments/list/ (checked 2026-09-03)

**Simple explanation:** Failed payments have different root causes: the customer, the merchant's setup, the bank, or Razorpay's systems.

**Hinglish explanation:** Payment fail hone ke different karan ho sakte hain: customer ki galti, merchant ki setup mein problem, bank issue, ya Razorpay ke servers mein problem.

**Fact:** If a customer's account is debited but no successful callback is received, the amount auto-refunds within T+7 working days.
- Source: https://razorpay.com/docs/payments/payments/faqs/ (checked 2026-09-03)

**Simple explanation:** If money leaves the customer's account but the bank doesn't confirm payment success, they automatically get the money back within a week.

**Hinglish explanation:** Agar customer ke account se paise nikle hain lekin bank ne confirm nahi kiya to 7 din mein paise apne aap return ho jate hain.

**Fact:** For UPI payments from PSP apps (Google Pay, PhonePe), refunds are not possible if bank details are not visible.
- Source: https://razorpay.com/docs/payments/refunds/faqs/ (checked 2026-09-03)

**Simple explanation (UNVERIFIED — exact error codes not fetched):** UNVERIFIED — Specific error codes (BAD_REQUEST_ERROR, etc.) mentioned in docs but complete code catalog needs manual review.

---

## 4. Refunds

**Fact:** Refunds available as full or partial. Regular refunds are free; instant refunds charge a small fee.
- Source: https://razorpay.com/docs/payments/refunds/faqs/ (checked 2026-09-03)

**Simple explanation:** You can refund customers fully or partially. Normal refunds are free, instant refunds cost a small amount.

**Hinglish explanation:** Aap puri ya aadhi refund de sakte ho. Normal refund free hai, instant refund mein chhota fee lagta hai.

**Fact:** Regular refunds take 5-7 business days via the same payment method used by customer. Refund status may stay "pending" during processing.
- Source: https://razorpay.com/docs/payments/refunds/faqs/ (checked 2026-09-03)

**Simple explanation:** Refunds usually take 5-7 business days to reach the customer's account or card.

**Hinglish explanation:** Refund 5-7 business din mein customer ke account ya card mein aa jata hai.

**Fact:** Refund statuses: pending, processed, failed, reversed. The `refund.processed` webhook is the most reliable way to track final status.
- Source: https://razorpay.com/docs/payments/refunds/faqs/ (checked 2026-09-03)

**Simple explanation:** Refunds go through pending → processed (success) or failed/reversed (error). Use webhooks to track this.

**Hinglish explanation:** Refund pending mein jata hai, phir processed (sफ़ल) ya failed (galat). Webhook se track karo.

**Fact:** Fees and taxes on captured payments are not reversed/returned on refunds.
- Source: https://razorpay.com/docs/payments/refunds/faqs/ (checked 2026-09-03)

**Simple explanation:** When you refund a customer, Razorpay's fees and taxes are not returned to you.

**Hinglish explanation:** Jab refund dete ho to Razorpay ka fee aur tax nahi lauta hota.

**Fact (UNVERIFIED):** UNVERIFIED — Refund eligibility: payments older than 6 months usually cannot be refunded (BAD_REQUEST_ERROR). Instant Refunds can attempt older payments for a fee. Exact age limit needs manual confirmation.

---

## 5. Payment Links

**Fact:** Payment Links are single-use payment collection tools for one-time payments from customers. They cannot be used for recurring payments (use Subscriptions instead).
- Source: https://razorpay.com/docs/payments/payment-links/faqs/ (checked 2026-09-03)

**Simple explanation:** A Payment Link is a unique URL you send to a customer to collect a one-time payment.

**Hinglish explanation:** Payment Link ek unique link hota hai jo aap customer ko bhejte ho taaki wo ek baar paise de sake.

**Fact:** Required field when creating: Amount (with currency). All other fields (customer details, description, reference ID) are optional.
- Source: https://razorpay.com/docs/payments/payment-links/create/ (checked 2026-09-03)

**Simple explanation:** You only need to specify the amount. Everything else is optional.

**Hinglish explanation:** Sirf amount zaroori hai. Baaki sab optional hai.

**Fact:** Expiry: You can set the date and time when the Payment Link should expire and become inactive.
- Source: https://razorpay.com/docs/payments/payment-links/create/ (checked 2026-09-03)

**Simple explanation:** You can set when a Payment Link expires and customers can no longer use it.

**Hinglish explanation:** Aap set kar sakte ho ki link kab expire ho jaye.

**Fact:** Notification options: Email notification or SMS notification (requires entering customer email or phone number).
- Source: https://razorpay.com/docs/payments/payment-links/create/ (checked 2026-09-03)

**Simple explanation:** You can send the Payment Link to customers via email or SMS.

**Hinglish explanation:** Aap customer ko payment link email ya SMS se bhej sakte ho.

**Fact:** Webhook events: `payment_link.paid`, `payment_link.cancelled`, `payment_link.expired`, `payment_link.partially_paid`.
- Source: https://razorpay.com/docs/payments/payment-links/faqs/ (checked 2026-09-03)

**Simple explanation:** Razorpay notifies you when a link is paid, cancelled, expired, or partially paid.

**Hinglish explanation:** Razorpay aapko batata hai jab link paid, cancelled, expired, ya partially paid ho.

---

## 6. Fees and Taxes

**Fact:** Razorpay charges a percentage-based fee per transaction (example: 2% on standard plan mentioned in general FAQs).
- Source: https://razorpay.com/docs/payments/payments/faqs/ (checked 2026-09-03)

**Simple explanation (UNVERIFIED — commercial rates):** UNVERIFIED — Exact commercial fee percentages are not detailed in /docs pages; these vary by merchant account type. Check your account dashboard or contact support for your rate.

**Fact:** GST at 18% is charged on fees for all payment methods except domestic card transactions ≤₹2,000.
- Source: https://razorpay.com/docs/payments/settlements/faqs/ (checked 2026-09-03)

**Simple explanation:** Razorpay adds 18% tax (GST) on top of its fees (except for small domestic card payments under ₹2,000).

**Hinglish explanation:** Razorpay apne fee par 18% tax lagata hai (chhote ₹2000 se kam card payments par nahi).

**Fact:** Fees and GST are deducted from your settlement amount before crediting to your bank account.
- Source: https://razorpay.com/docs/payments/settlements/faqs/ (checked 2026-09-03)

**Simple explanation:** Your settlement amount = Total payment - fees - tax.

**Hinglish explanation:** Settlement amount = Total payment - fee - tax.

---

## 7. Reports

**Fact:** Available reports: Payments, Settlements, and Settlement Reconciliation reports. Formats: CSV, XLS, XLSX.
- Source: https://razorpay.com/docs/payments/dashboard/reports/ (checked 2026-09-03)

**Simple explanation:** You can download transaction data as CSV, Excel, or XLSX files.

**Hinglish explanation:** Aap transaction data ko CSV, Excel ya XLSX mein download kar sakte ho.

**Fact:** Reports can be scheduled for automatic email delivery at daily, weekly, or monthly frequency.
- Source: https://razorpay.com/docs/payments/dashboard/reports/ (checked 2026-09-03)

**Simple explanation:** Razorpay can automatically email you reports on a schedule you choose.

**Hinglish explanation:** Razorpay apne aap report aapke email par bhej sakta hai daily, weekly, ya monthly.

**Fact:** Reports support custom date ranges (specific day, month, or time frame selection).
- Source: https://razorpay.com/docs/payments/dashboard/reports/ (checked 2026-09-03)

**Simple explanation:** You can select any date range for your reports.

**Hinglish explanation:** Report ke liye koi bhi date range choose kar sakte ho.

---

## 8. Disputes and Chargebacks

**Fact:** A dispute occurs when a customer or issuing bank questions payment validity due to unauthorized charges, undelivered goods, or excessive billing.
- Source: https://razorpay.com/docs/payments/disputes/ (checked 2026-09-03)

**Simple explanation:** A dispute is when a customer or bank says "this payment shouldn't have happened."

**Hinglish explanation:** Dispute tab hota hai jab customer ya bank kahte hain "ye payment galat tha."

**Fact:** Five dispute phases: Fraud → Retrieval (soft chargeback) → Chargeback → Pre-Arbitration → Arbitration (card network, typically expensive).
- Source: https://razorpay.com/docs/payments/disputes/ (checked 2026-09-03)

**Simple explanation:** Disputes escalate through phases. Early stages (Retrieval) are easier to win; later stages (Arbitration) are costly.

**Hinglish explanation:** Disputes alag alag levels mein jaate hain. Shuru mein easy hai, aakhir mein mehenga ho jata hai.

**Fact:** Dispute statuses in Razorpay: Open → Under Review → Won (documents accepted) / Lost (documents rejected) / Closed (fraud resolved).
- Source: https://razorpay.com/docs/payments/disputes/ (checked 2026-09-03)

**Simple explanation:** A dispute starts as "Open," then gets reviewed, and ends as Won, Lost, or Closed.

**Hinglish explanation:** Dispute open se shuru hota hai, review hota hai, phir won/lost/closed ban jata hai.

**Fact:** Merchants can accept (customer refunded) or contest (submit evidence) disputes via Dashboard or APIs.
- Source: https://razorpay.com/docs/payments/disputes/ (checked 2026-09-03)

**Simple explanation:** You can either give the customer a refund or fight the dispute with evidence.

**Hinglish explanation:** Aap refund de sakte ho ya evidence deke dispute ka muqabla kar sakte ho.

---

## 9. Settlement Timelines

**Fact:** Standard domestic settlement cycle: T+2 working days (T = capture date). Excludes weekends (2nd/4th Saturday, Sunday) and bank holidays.
- Source: https://razorpay.com/docs/payments/settlements/ (checked 2026-09-03)

**Simple explanation:** Money from captured payments settles in your account within 2 business days (not counting weekends/holidays).

**Hinglish explanation:** T+2 working din mein paise settle ho jate hain (weekends aur holidays nahi count).

**Fact:** International payment settlements: T+7 working days cycle.
- Source: https://razorpay.com/docs/payments/settlements/faqs/ (checked 2026-09-03)

**Simple explanation:** International payments take longer: about 7 business days to settle.

**Hinglish explanation:** International payment T+7 din mein settle hota hai.

**Fact:** Partial settlements occur when live balance drops below scheduled settlement amount; Razorpay calculates the correct amount and ensures settlements aren't skipped.
- Source: https://razorpay.com/docs/payments/settlements/ (checked 2026-09-03)

**Simple explanation:** If your balance is less than expected, Razorpay settles whatever is available without skipping cycles.

**Hinglish explanation:** Agar balance kam hai to Razorpay jitna possible hai utna settle kar deta hai.

**Fact:** Prerequisites for settlement: KYC approval, full account activation, and captured payment status.
- Source: https://razorpay.com/docs/payments/settlements/ (checked 2026-09-03)

**Simple explanation:** Your account must be fully verified and payments must be captured for settlements to happen.

**Hinglish explanation:** Account pura activate hona chahiye aur payment capture hona chahiye settlement ke liye.

---

## Summary of Verification Status (10 items)

1. **VERIFIED** ✓ Settlement definition, T+2 cycle, deductions (fees, GST, refunds, disputes)
2. **VERIFIED** ✓ Payment lifecycle: created → authorized → captured → settled
3. **VERIFIED** ✓ Failed payment error classification (customer, business, gateway, Razorpay sources)
4. **VERIFIED** ✓ Refund types (full/partial), timelines (5-7 days), status tracking via webhooks
5. **VERIFIED** ✓ Payment Links: one-time, required amount field, expiry, email/SMS notifications
6. **UNVERIFIED** — Specific commercial fee percentages vary by account; docs only mention "2%" generic example and direct to external pricing page
7. **VERIFIED** ✓ GST 18% on fees (except domestic cards ≤₹2,000); reports in CSV/XLS/XLSX with scheduling
8. **VERIFIED** ✓ Disputes: five phases, four statuses, accept/contest options
9. **VERIFIED** ✓ Settlement timelines: domestic T+2, international T+7, partial settlement logic
10. **UNVERIFIED** — Exact refund age limit (6-month cutoff mentioned but eligibility edge cases need manual check)

**Note:** All verified claims linked to https://razorpay.com/docs pages checked 2026-09-03. Unverified items either absent from official /docs or require account-specific information.
