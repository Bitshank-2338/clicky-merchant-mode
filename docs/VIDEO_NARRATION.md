# Video Narration Script

Independent hackathon prototype. Not an official Razorpay product.

Word-for-word narration for `video/clicky-merchant-mode-demo.mp4`, with the
timings the shipped text-to-speech track actually produced.

To re-record in your own voice: render silent visuals with
`python -m video.make_video --frames`, then narrate over them. Keep roughly
to the per-scene durations below and the visuals will stay in sync.

**14 scenes · 574 words · 4m 23.1s total**

| # | Scene | Starts | Length |
|---|---|---|---|
| 1 | Clicky Merchant Mode | 0:00.0 | 15.1s |
| 2 | The problem is not documentation | 0:15.5 | 15.0s |
| 3 | Not a chatbot. A teacher that reads your screen. | 0:30.8 | 18.8s |
| 4 | Ask in Hinglish | 0:50.0 | 17.7s |
| 5 | The model is never allowed to author a number | 1:08.0 | 20.4s |
| 6 | Guide me, step by step | 1:28.8 | 22.4s |
| 7 | Teaches the form. Never submits it. | 1:51.5 | 14.5s |
| 8 | Asked to just do it, it refuses | 2:06.4 | 16.8s |
| 9 | On your real dashboard, it uses your real numbers | 2:23.6 | 23.8s |
| 10 | When it cannot see, it says so | 2:47.7 | 12.5s |
| 11 | Privacy is the default, not a setting | 3:00.6 | 24.4s |
| 12 | Measured, not claimed | 3:25.3 | 28.3s |
| 13 | It works with the model switched off | 3:54.0 | 14.9s |
| 14 | Clicky Merchant Mode | 4:09.3 | 13.5s |

---

## 1. Clicky Merchant Mode

`0:00.0` · 15.1s · 37 words · layout: title

> A shopkeeper collects ten thousand rupees through Razorpay. Nine thousand two hundred and sixty four arrives in the bank. Nothing on the screen explains the missing seven hundred and thirty six rupees in words they actually use.

## 2. The problem is not documentation

`0:15.5` · 15.0s · 37 words · layout: quote

**On screen:**
- Settlements that are smaller than the day's collection
- Payments marked failed, with no idea if the customer was charged
- A refund they are afraid to click
- Reports the accountant asked for

> Small merchants are not looking for documentation. They are looking at a dashboard right now, and they need someone to point at it. A support chatbot in another tab cannot help, because it cannot see the screen.

## 3. Not a chatbot. A teacher that reads your screen.

`0:30.8` · 18.8s · 45 words · layout: quote

**On screen:**
- Reads the active window — the page you are already on
- Explains it in Hindi, Hinglish or English
- Points the cursor at the exact element you need next
- Never moves your money

> Merchant Mode is built into Clicky, a desktop companion that lives beside your cursor. It reads the window you are already looking at, explains it in your own language, and points at what you need next. It is read only. It never moves your money.

## 4. Ask in Hinglish

`0:50.0` · 17.7s · 39 words · layout: split

**On screen — merchant asks:** "Mere payment ka settlement kam kyon aaya?"

**On screen — Clicky replies:** Is settlement period mein aapke customers ne ₹10,000 diye the. ₹200 fees, ₹36 fees par tax aur ₹500 refunds katne ke baad, aapke bank mein ₹9,264 aata hai. Matlab paisa aane se pehle total ₹736 kata hai.

**Highlights, in order:** settlement.gross_amount, settlement.fees, settlement.tax, settlement.refunds, settlement.net_amount

> The merchant asks, in Hinglish, why their settlement came up short. Clicky reads the page, does the arithmetic in exact paise, and highlights each line in turn: gross amount, fees, tax on those fees, refunds, and the net settlement.

## 5. The model is never allowed to author a number

`1:08.0` · 20.4s · 45 words · layout: quote

**On screen:**
- All money arithmetic happens in integer paise, in code
- The language model may only reword — never recalculate
- Any answer quoting an unbacked figure is discarded
- Measured hallucination rate: 0%

> This is the part that matters most. Every rupee figure is computed in code. The model may only improve the wording. If it changes so much as one digit, the answer is thrown away and the verified version is used instead. Measured hallucination rate: zero.

## 6. Guide me, step by step

`1:28.8` · 22.4s · 51 words · layout: split

**On screen — merchant asks:** "Kal ke failed payments dikhao"

**On screen — Clicky replies:** Aapke 4 payment fail hue hain, total ₹5,049 ke. Reasons: 1 × account mein paise kam the, 1 × galat OTP daala gaya, 1 × customer ne cancel kar diya, 1 × bank par poora nahi hua. Failed payment ka matlab hai paisa aap tak pahuncha hi nahi. Agar customer ke account se kat gaya tha, to bank aam taur par khud wapas kar deta hai. Dobara try karne ko keh sakte hain, par pakka nahi kaha ja sakta ki successful hoga.

**Highlights, in order:** nav.payments, payments.date_filter, payments.status_filter, payments.failed_option, payments.apply_filter, payments.error_reason

> Guide Me does not dump five steps at once. It highlights the next control, explains why it matters, waits, re-checks the screen, and only then continues — to the payments page, the date filter, the failed status, the failure reason. And it never promises a retry will succeed, because nobody can.

## 7. Teaches the form. Never submits it.

`1:51.5` · 14.5s · 30 words · layout: split

**On screen — merchant asks:** "Mujhe payment link banana sikhao"

**On screen — Clicky replies:** Payment link ek chhota web page hai jo aap customer ko bhejte hain taaki wo aapko paisa de sakein. Sirf amount zaroori hai. Customer ka naam, email, phone sab optional hai. Aap set kar sakte ho ki link kab expire ho jaye. Uske baad customer use nahi kar sakta.

**Highlights, in order:** link.amount, link.description, link.expiry, link.customer_name, link.customer_contact, link.preview

> Asked to teach payment links, it walks through every field, then stops. The final step says: you press Create yourself. This last step is yours. Clicky will not press it.

## 8. Asked to just do it, it refuses

`2:06.4` · 16.8s · 41 words · layout: split

**On screen — merchant asks:** "Refund kar de abhi!"

**On screen — Clicky replies:** Main ye kaam khud nahi kar sakti. Main aapko har step dikha sakti hoon, lekin final button aapko hi dabana hoga — paisa aapka hai.

**Highlights, in order:** nav.payments, payments.table, refunds.table, refunds.type

> Told to just issue a refund, it refuses, explains why, and teaches the steps instead. Read only is not a policy here — the adapter interface has no create, refund or send method at all, so there is nothing to call.

## 9. On your real dashboard, it uses your real numbers

`2:23.6` · 23.8s · 60 words · layout: split

**On screen — merchant asks:** "Mere payment ka settlement kam kyon aaya?"

**On screen — Clicky replies:** Is screen par total ₹47,320 dikh raha hai. ₹946 razorpay fees, ₹170 tax on fees katne ke baad ₹46,204 aapke bank jaata hai. Matlab paisa aane se pehle total ₹1,116 kata hai. Ye numbers aapki screen se padhe gaye hain, demo data se nahi.

**Highlights, in order:** settlement.gross_amount, settlement.fees, settlement.tax, settlement.refunds, settlement.adjustments, settlement.net_amount

> This one caught us out in testing. On a real dashboard, demo data belongs to a different account — numbers that look right and belong to somebody else. So on a live dashboard the demo adapter is bypassed entirely: amounts are read off the screen, and Clicky says so. If it cannot read them, it gives no number at all.

## 10. When it cannot see, it says so

`2:47.7` · 12.5s · 27 words · layout: split

**On screen — merchant asks:** "settlement kam kyon aaya"

**On screen — Clicky replies:** Yahan abhi kuch nahi hai, isliye samjhane ko kuch nahi hai.

> An empty dashboard produces no invented rows. A data error produces an admission, not a guess. Saying I do not know is a first class answer here.

## 11. Privacy is the default, not a setting

`3:00.6` · 24.4s · 48 words · layout: quote

**On screen:**
- Active window only — never the whole desktop
- Screen access is opt-in, per session
- Screenshots are never written to disk
- PII masked before text reaches a model, a log or the screen
- Local inference by default; one button stops everything

> Privacy is structural. Only the active window is captured. Access is opt in and revocable with one button. Screenshots are never written to disk. Phone numbers, emails, cards and customer names are masked before the text reaches a model, a log, or the screen. Measured privacy violations: zero.

## 12. Measured, not claimed

`3:25.3` · 28.3s · 55 words · layout: metrics

**On screen:** 100% Page detection · 100% Factual accuracy · 96.8% Highlight recall · 100% Language detection · 100% Sensitive-action blocking · 100% Step completion · 0% Hallucination rate · 0 Privacy violations

> Every number here comes from a real evaluation over thirty six seeded tasks, reproducible with one command. Page detection and factual accuracy, one hundred percent. Highlight recall, ninety seven. Zero hallucinations, zero privacy violations. Intent detection sits at seventy eight percent, and we report that honestly rather than editing the answer key to flatter it.

## 13. It works with the model switched off

`3:54.0` · 14.9s · 30 words · layout: quote

**On screen:**
- Deterministic templates in English, Hindi and Hinglish
- Fallback answers are labelled as fallback
- Fallback success rate: 100%
- Everything in this video was produced with Ollama disabled

> One last thing. Everything you just watched ran with the local model switched off. The deterministic path is the default, not a degraded mode. Fallback success rate: one hundred percent.

## 14. Clicky Merchant Mode

`4:09.3` · 13.5s · 29 words · layout: closing

> Clicky Merchant Mode teaches merchants from the screen they are already using, speaks their language, guides them visually, and keeps them in control of every sensitive action. Thank you.

