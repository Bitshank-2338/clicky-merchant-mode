# Clicky Merchant Mode — Three-Minute Demo Script

This is an independent hackathon prototype, not an official Razorpay product.

## Pre-Demo Setup

Run these commands in the project root before presenting:

```bash
# Install dependencies
pip install -r requirements.txt

# Start the FastAPI sidecar (in terminal 1)
python -m merchant.server

# In terminal 2, start the mock dashboard
cd mockdashboard
npm install
npm start  # runs on http://localhost:3000

# In terminal 3, start Clicky (or use the existing running instance)
python main.py
```

Verify:
- FastAPI sidecar running on `http://127.0.0.1:8756`
- Mock dashboard at `http://localhost:3000`
- Clicky window open and ready

## Pre-Flight Checklist

- [ ] Clicky window is in focus.
- [ ] Mock dashboard is open in a browser (visible or ready to switch to).
- [ ] Ollama is NOT running (so fallback templates work). If Ollama is running, you'll see warmer phrasing; the demo still works.
- [ ] Audio is working or TTS is disabled in settings.
- [ ] You can see the privacy indicator in the Clicky panel.

## Three-Minute Flow

### 1. **Enable Merchant Mode** (0:00–0:15)

**What you do:**
- Focus the Clicky window.
- Point at the Merchant Mode toggle in the panel.
- Say: "I'm going to enable Merchant Mode so Clicky can read the screen I'm looking at."
- Click "Enable" (or equivalent permission button).

**What you explain:**
- "Notice the Privacy indicator says 'Privacy ON — screen access not granted' before I click.
  After I click, it says 'Privacy ON — active window only, nothing saved'. The screen is never stored to disk. Clicky only reads what I am actively looking at."

**If it fails:** "The permission gate didn't activate — this usually means the environment is not configured for active-window capture. We are on Windows; if this is running on another OS, that feature is not available."

---

### 2. **The Classic Small-Merchant Question** (0:15–0:50)

**Setup:**
- Point to the mock dashboard (or focus it).
- Make sure the "Settlements" tab is visible, showing the demo data.
- The first settlement row shows:
  - Gross amount: ₹10,000 (1000000 paise in the seed data)
  - Razorpay fees: ₹200 (20000 paise)
  - Tax on fees: ₹36 (3600 paise)
  - Refunds: ₹500 (50000 paise)
  - Net settlement: ₹9,264 (926400 paise)

**What you say in Clicky (in Hinglish):**
"Mere settlement mein paisa kam kyon aaya?"

(Translation: "Why is my settlement short?")

**What happens:**
- Clicky reads the active window (the mock dashboard).
- It extracts the settlement row.
- It computes the math: gross ₹10,000 minus fees ₹200, minus tax ₹36, minus refunds ₹500, equals ₹9,264.
- It highlights each field on the screen (gross, fees, tax, refunds, net).
- It explains: "Your customers paid ₹10,000 in this settlement period. After ₹200 fees, ₹36 tax on fees, and ₹500 refunds, the amount that reaches your bank is ₹9,264. So ₹736 in total was taken out before the money reached you."

**What you point out:**
- "Every number on screen is highlighted. Clicky is pointing at what it actually sees, not guessing."
- "The math is shown. The merchant can verify it line by line."
- "The language is simple and in Hinglish — the merchant doesn't need to understand accounting."

**If Ollama is running:** The phrasing will be warmer (e.g., "Your customers paid ₹10,000. Razorpay took ₹236 in fees and taxes. You also issued ₹500 in refunds. So you received ₹9,264.").
Explain: "When Ollama is available, Clicky improves the wording while keeping the numbers identical."

---

### 3. **Failed Payments** (0:50–1:15)

**Setup:**
- In the mock dashboard, switch to the "Payments" tab.
- Select the "Failed" status filter and apply it.
- You should see 4 failed payments (from the `multiple_failed_payments` scenario).

**What you say:**
"Kal ke failed payments dikhao. Mujhe samjhao in par kya hua."

(Translation: "Show me yesterday's failed payments. Explain what happened.")

**What happens:**
- Clicky detects the intent (failed payments) and the page (payments).
- It retrieves the failed payments from the dashboard.
- It explains: "You have 4 failed payment(s) worth ₹5,049. Reasons shown: 1 × not enough balance, 1 × wrong OTP entered, 1 × cancelled by the customer, 1 × not completed at the bank. A failed payment means the money never reached you. If the customer was debited, banks usually return it on their own. Asking them to try again may work, but nobody can promise it will."
  - (In Hinglish the same answer reads: "Aapke 4 payment fail hue hain, total ₹5,049 ke. Reasons: 1 × account mein paise kam the, …")
- It highlights the failed rows and the "Failure reason" column.

**What you point out:**
- "Each failure is different: bank declined, customer cancelled, invalid OTP, insufficient funds."
- "Clicky doesn't promise a retry will work — that's honest uncertainty."

---

### 4. **Form Guidance: Create a Payment Link** (1:15–1:50)

**Setup:**
- In the mock dashboard, go to the "Payment Links" tab.
- You will see a form with fields: Amount, Description, Expire by, Customer name, Customer contact, etc.

**What you say:**
"Mujhe payment link banana sikhao."

(Translation: "Teach me to make a payment link.")

**What happens:**
- Clicky detects intent (`CREATE_PAYMENT_LINK_TUTORIAL`) and the page (`PAYMENT_LINKS`).
- It enters "Guide Me" mode and walks through the form step by step:
  1. "Fill in the amount the customer will pay (required)."
  2. "Write a short description — what is this for? (optional, but helpful)."
  3. "When should this link expire? (optional)"
  4. "Who is this for? (optional, but helpful for your records)"
  5. "Their phone number or email? (optional)"
- Each step highlights the corresponding field on the dashboard.
- It never clicks "Create" or submits anything.

**What you explain:**
- "Clicky guides step-by-step. The merchant stays in control and clicks every button themselves."
- "Each step is highlighted on the actual form, so there is no confusion about which field to fill."

**What you do:**
- Walk through 2–3 steps verbally.
- Then say: "And so on — the merchant fills each field and Clicky points along the way. At the end, the merchant clicks 'Create Payment Link' themselves in the dashboard."

---

### 5. **A Sensitive Action — The Refusal** (1:50–2:10)

**What you say:**
"Refund kar do."

(Translation: "Just do the refund for me.")

**What happens:**
- Clicky detects the demand (`issue_refund` in `NEVER_AUTOMATED`).
- It refuses: "I will not do this for you. I can show you every step, but the final button has to be yours — it is your money." (Or the Hinglish version: "Main ye kaam khud nahi kar sakti...")
- It then offers: "Let me show you how to issue a refund yourself."

**What you explain:**
- "Merchant Mode will never modify your account, ever. It is read-only by design. If you ask it to 'just do it', it says no and teaches you instead."
- "The safety guarantee is structural — there is no way to trick Clicky into executing an action."

---

### 6. **The Audit Trail** (2:10–2:25)

**What you do:**
- Open the Audit Log panel in Clicky (usually a side panel or bottom panel showing recent events).
- Scroll through and point out entries:
  - "question: settlement..."
  - "answer: explanation with facts..."
  - "action_blocked: refund kar do"

**What you explain:**
- "Every question, explanation, and refusal is logged. The merchant can audit what Clicky did."
- "Sensitive data is masked in the log — names become initials, phone numbers show only the last 4 digits. The log itself becomes safe, never a leak."

---

### 7. **Privacy Recap** (2:25–3:00)

**What you point out:**
- The Privacy indicator in the panel: "Privacy ON — active window only, nothing saved."
- The mask count: "Masked fields this session: 12" (or your actual number).
- The capture count: "Captures this session: 5" (or your actual number).

**What you explain (final message):**
"Clicky Merchant Mode teaches merchants from the screen they are already using. It speaks their language — English, Hindi, Hinglish. It guides them visually, points at the actual pixels, and keeps them in control of every rupee. Privacy is on by default. Sensitive data is masked. Nothing is stored. The merchant can audit everything. And if they ask Clicky to move money, Clicky says no."

**Closing line (if you have a final thought):**
"This is a hackathon prototype, not an official Razorpay product. It shows how an AI can be trustworthy: transparent, honest about uncertainty, and respectful of control."

---

## If Something Fails Live

| Failure | What to Say |
|---------|------------|
| Clicky doesn't recognize the language | "Clicky supports English, Hindi, and Hinglish. Let me rephrase in English." |
| The highlight doesn't appear or is wrong | "Merchant Mode uses three methods to find elements: DOM coordinates, OCR text search, and vision-model fallback. If all three fail, it tells the merchant 'I could not read that from your screen' rather than pointing at a guess." |
| Ollama is running and the answer is refined phrasing | "Ollama is running locally, so Clicky improves the wording while keeping the math exact." |
| Ollama is not running | "That's fine — Clicky falls back to deterministic templates, which are still accurate. You don't need Ollama to get correct answers." |
| The settlement numbers don't match | "Check that the mock dashboard and the seed file are in sync (`merchant/seed/dashboard_seed.json`). They should show the same numbers." |
| Privacy indicator shows "not granted" | "Click the Enable button. The merchant has to explicitly grant permission to read the screen." |

---

## Demo Data Reference

All numbers come from `merchant/seed/dashboard_seed.json`, scenario `settlement_lower_than_gross`:

| Component | Paise | Rupees |
|-----------|-------|--------|
| Gross collected | 1,000,000 | ₹10,000 |
| Razorpay fees | 20,000 | ₹200 |
| Tax on fees | 3,600 | ₹36 |
| Refunds issued | 50,000 | ₹500 |
| **Net settled** | **926,400** | **₹9,264** |

