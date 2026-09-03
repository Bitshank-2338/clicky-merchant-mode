# Clicky Merchant Mode — Privacy Design

This is an independent hackathon prototype, not an official Razorpay product.

Merchant Mode's privacy posture is designed so that a merchant can audit it by reading one short file (`merchant/privacy.py`). This document explains how the implementation works.

## Opt-In Permission Gate

Screen reading is off by default. A merchant explicitly grants permission once per session by clicking "Enable" in the Merchant Mode panel.

**How it works** (`merchant/privacy.py`):
- `PrivacyState.grant_permission()` sets `_capture_allowed = True`.
- Every pipeline call checks `require_capture_permission(state)` before attempting capture.
- If permission has not been granted, a `PermissionDenied` exception is raised and the merchant sees: *"Turn on Merchant Mode screen reading to continue."*
- The panel displays the current state: *"Privacy ON — screen access not granted"* until the merchant acts.

**A second opt-in for cloud inference** (`PrivacyState.allow_cloud_inference`):
- Local inference (Ollama) is the default.
- Sending screen text to a cloud model requires a separate `allow_cloud_inference(True)` call.
- The permission prompt includes the `CLOUD_WARNING`: *"This will send text read from your screen to a cloud AI service."*

## Active-Window-Only Capture

Merchant Mode never reads the whole desktop, never reads a second monitor, never reads anything except the window the merchant is actively using.

**How it works** (`screen/capture.py`):
- `capture_active_window()` uses `ctypes.windll` (Windows only) to locate the foreground window.
- `active_window_rect()` calls `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` to get the exact bounds, avoiding Windows' invisible resize borders which would skew coordinates by ~7px.
- The window is captured in its entirety but coordinates are tracked relative to that window's top-left, not the virtual desktop.
- The result is a `WindowShot` carrying physical size, DPI scale, and logical-screen origin so highlights can be positioned accurately.

**This is an additive change**, not a replacement:
- Clicky's original `capture_all_screens()` is untouched (`screen/capture.py`, lines 69–110).
- `capture_active_window()` is new code, so the existing feature is not disrupted.

## No Screenshot Persistence

Screenshots are never written to disk. The bytes live in memory only, inside the function that processes them, and are discarded when the function returns.

**How it works** (`screen/capture.py`):
- `WindowShot` carries `jpeg_bytes: bytes` in memory.
- The base64-encoded JPEG (`base64_jpeg: str`) is passed to OCR and the LLM for reasoning.
- Once the response is generated, the bytes are not retained.
- `PrivacySnapshot.screenshots_stored` is always 0 (a structural invariant enforced by the audit log).

**Structural test**: Searching the codebase for file-write operations (`open(`, `write(`, `Path.write_bytes`) that target image files finds only `mss.tools.to_png()` in Clicky's existing (pre-Merchant-Mode) screenshot feature, which is unrelated.

## Sensitive Data Masking

Every piece of text extracted from the screen is masked before it leaves the function that produced it. This is the single chokepoint for PII.

**What is masked** (`merchant/masking.py`, `_RULES` list, lines 66–105):
- **Card numbers**: 13–19 digits, optionally spaced; also masked-with-stars forms like `4111 **** **** 1111`.
- **Aadhaar**: 12 digits in 4-4-4 format.
- **UPI VPA**: `handle@provider` form.
- **Email addresses**: standard format.
- **Phone numbers**: Indian landlines and mobiles, +91 or 0 prefix, spaces/dashes allowed.
- **Bank account numbers**: 9–18 digits when labelled as `acc.`, `account`, etc.
- **PAN**: 5 letters, 4 digits, 1 letter.
- **IFSC**: 4 letters, 0, 6 alphanumerics.
- **API keys / Secrets / Bearer tokens**: Razorpay keys (`rzp_live_`, `rzp_test_`), generic SK/PK keys, Bearer tokens, and key-like assignments.

**Field-level masking** for known PII fields:
- `customer_name` / `name` → initials only: `"Rohit Verma"` → `"R. V."`
- `customer_contact` / `contact` / `phone` → last 4 digits visible: `"+919812345678"` → `"+91 ****** 5678"`
- `customer_email` / `email` → first letter + domain: `"rohit.verma@example.com"` → `"r***@example.com"`

**Over-masking is deliberate**. The code prefers to hide a harmless string (like a bank account in a memo field) rather than risk leaking a card number.

**Currency figures are preserved**. A settlement of ₹9,264 remains readable after masking because rupees are not PII.

## Local-First Inference

Clicky uses Ollama (a local AI model running on the merchant's machine) by default. No screen data leaves the machine unless the merchant explicitly opts in.

**How it works**:
- When Ollama is reachable, `merchant/explain.py` sends screen-derived facts to it with instructions to improve phrasing only.
- The result is checked by `verify_no_invented_numbers`: any response that invents a currency figure not in the fact list is discarded and replaced with the deterministic template.
- When Ollama is absent or unreachable, Merchant Mode falls back to deterministic templates — still accurate, just templated phrasing.

**Cloud inference is opt-in**:
- `PrivacyState.allow_cloud_inference(True)` must be called explicitly.
- The merchant sees the `CLOUD_WARNING` before confirming.
- Only the masked screen text is sent (names → initials, phone → last 4 digits, emails → `r***@domain`).

## Stop Monitoring — The Panic Button

A single button in the panel stops everything immediately.

**How it works** (`merchant/privacy.py` + `merchant/pipeline.py`):
- `PrivacyState.stop_monitoring()` sets `_capture_allowed = False`, `_monitoring = False`, and `_cloud_allowed = False`.
- This is thread-safe (protected by `_lock`).
- The pipeline checks `state.monitoring` on every request; a stopped state means no capture, no cloud calls, no inference.
- `MerchantPipeline.stop_monitoring()` also records the event in the audit log (`KIND_STOP`).

## Audit Log Is Not a Leak

Every merchant question, every explanation, every capture and every action refusal is recorded. The audit log must never become a PII leak.

**How it works** (`merchant/audit.py`):
- `AuditLog.record(kind, detail, outcome)` masks every detail string first: `detail = mask_text(detail).text`.
- Then it checks: `contains_unmasked_pii(safe)`. If any PII survived masking, the entire entry is replaced with `REDACTED`.
- The decision is: fail loudly (refuse the entire entry) rather than leak quietly.
- Entries are append-only in memory for the session.
- To disk (optional): only if `MERCHANT_AUDIT_PATH` is set (not by default).

**Example**: If somehow a card number reached an audit event, the event would read:
```
[REDACTED — entry withheld because it still contained sensitive data]
```

Not a partial entry, not a masked-and-written entry — the whole thing is rejected.

## What We Do NOT Collect

- **Screenshots**: never stored to disk, never persisted after analysis.
- **Raw customer data**: names, phone numbers, emails are masked before any processing.
- **Financial transaction details** beyond what is displayed on the merchant's own dashboard.
- **Browsing history** or other application activity.
- **Cookies** from the Razorpay dashboard.
- **Keystroke logs** or mouse-movement tracking.
- **The merchant's account credentials** (API keys are read from environment variables, never captured from the screen).

## What Leaves Your Machine

| Scenario | What Leaves | Conditions |
|----------|-------------|-----------|
| **Default** | Nothing | Ollama inference; all processing local. |
| **With Ollama unavailable** | Nothing | Falls back to deterministic templates; no network call. |
| **Cloud inference enabled** | Masked screen text only | Merchant explicitly granted `allow_cloud_inference`; only text that has passed masking. |
| **Razorpay Test Mode** | API queries + responses | Read-only GET requests to the Razorpay API; encrypted by HTTPS. |
| **Error reports** | Error message (no context) | On opt-in (unimplemented in current build). |

**Example of masked data leaving the machine**:
- Screen shows: *"Customer Rohit Verma at +919812345678 paid ₹500."*
- After masking: *"Customer R. V. at +91 ****** 5678 paid ₹500."*
- Sent to cloud model: only the masked version.

## Privacy Transparency in the UI

The panel displays a `PrivacySnapshot` in real time:
- **Captures this session**: count of windows read.
- **Masked fields this session**: count of PII items redacted before processing.
- **Screenshots stored**: always 0 (a structural guarantee, not aspirational).
- **Last capture at**: timestamp of the most recent window read.
- **Status text**: summarises the current posture — *"Privacy ON — active window only, nothing saved"* when running normally.

This transparency lets the merchant audit what Clicky is actually doing.

