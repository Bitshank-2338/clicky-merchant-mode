# Buildathon Submission Checklist

Independent hackathon prototype. Not an official Razorpay product.

**Submission form:** https://forms.gle/d9r2gvxp8cmoZhon9
**Deadline: 5 September 2026.** Verified from secondary sources, not from the
official page — the razorpay.com/buildathon page itself does **not** state a
date. Confirm it on the form before relying on it.

---

## What the official page actually asks for

Quoted from razorpay.com/buildathon:

> a public repo · a 5 minute pitch video · the architecture

Plus: *"Build an agent … on Razorpay test-mode APIs."*

Programme facts stated on the page:

- **Students only.** It is an application route to a 6- or 12-month AI Builder
  internship at Razorpay Bangalore, ₹75,000/month, in person from September.
- **Five tracks.** Ours is the **Open Track** — *"Build what you believe should
  exist."*
- Track 2 carries an explicit constraint (defence-only); the Open Track has no
  stated constraint on the page.

## Status

| Requirement | Status | Where |
|---|---|---|
| Public repo | **Ready — needs one command to publish** | see below |
| 5-minute pitch video | **Done — 4m18s** | `video/clicky-merchant-mode-demo.mp4` |
| Architecture | **Done** | `docs/ARCHITECTURE.md` |
| Built on Razorpay test-mode APIs | **Done (read-only)** | `merchant/adapters/razorpay_test.py` |
| Student eligibility | **You must confirm** | — |

## Publishing the repository

Everything is committed. This one command creates the public repo and pushes:

```bash
gh repo create clicky-merchant-mode --public --source=. --remote=merchant --push --description "Clicky Merchant Mode — a privacy-first visual and voice teacher that helps small merchants understand and operate the Razorpay dashboard. Razorpay AI Buildathon, Open Track."
```

Then confirm it is genuinely public and that the README renders:

```bash
gh repo view Bitshank-2338/clicky-merchant-mode --web
```

Before submitting, sanity-check that no secret slipped in:

```bash
python -m pytest tests/test_safety_confirmation.py -q
```

## Hosting the video

The page does not specify a platform. Safest is an **unlisted YouTube link**
(no time limit, plays anywhere, no viewer sign-in). Loom's free tier caps
videos at five minutes, which this only just fits under — YouTube avoids the
risk. Whatever you choose, open the link in a private window before submitting
to confirm a stranger can actually watch it.

## Gaps to close before you submit

These need a human, and are listed in the order they will cost you marks.

1. **Confirm the deadline and any format rules on the form itself.** The public
   page states neither.
2. **Consider re-recording the narration in your own voice.** The shipped video
   uses text-to-speech. It is clear and correctly paced, but a real voice reads
   as more committed for what is effectively an internship application. The
   word-for-word script is in `docs/VIDEO_NARRATION.md` and the visuals can be
   re-rendered without audio (`python -m video.make_video --frames`) so you can
   narrate over them.
3. **Record 20–30 seconds of the actual desktop app**, if you can. The current
   video is a rendered explainer — accurate, since every string and figure comes
   from the live pipeline, but rendered. A short clip of Clicky's real overlay
   pointing at your screen would answer the obvious judge question, *"does this
   actually run?"* Run `python main.py`, open the mock dashboard, and ask
   *"Mere payment ka settlement kam kyon aaya?"*
4. **Add your name, college and contact** to the README. It is an internship
   application; right now the repo does not say who built it.
5. **Optionally run it against a real test-mode key.** Set `RAZORPAY_KEY_ID` /
   `RAZORPAY_KEY_SECRET` and `MERCHANT_ADAPTER=razorpay_test`. The brief says
   "on Razorpay test-mode APIs", and being able to say you exercised it against
   a live test account is stronger than saying the adapter exists. The adapter
   is read-only and refuses non-`rzp_test_` keys.
6. **Install Tesseract** if you want the video's live-dashboard claim to be
   demonstrable on your own machine. Without it, element targeting on the real
   dashboard degrades to lower-accuracy tiers.

## What to write in the form's description field

A suggested short version, all of which is defensible from the repo:

> Clicky Merchant Mode is a privacy-first visual teacher for the Razorpay
> dashboard. It reads the window a merchant is already looking at, explains it
> in Hindi, Hinglish or English, and points the cursor at the exact element
> they need next.
>
> It is read-only by construction — the data adapter has no create, refund or
> send method, so there is nothing to call. Every rupee figure is computed in
> integer paise in code; the language model may only reword, and any answer
> quoting an unbacked figure is discarded. On a live Razorpay dashboard the
> demo data is bypassed entirely and amounts are read off the screen, or not
> given at all.
>
> Built additively on Clicky, my existing open-source desktop companion: new
> behaviour arrives as new files plus appended symbols, and the one place
> existing logic changed is an unrelated upstream bug fix.
>
> 324 tests. Evaluated over 36 seeded merchant tasks: 100% page detection, 100%
> factual accuracy, 96.8% highlight recall, 0% hallucination, 0 privacy
> violations, 100% fallback success with the local model disabled. Evaluated on
> synthetic data; does not represent production performance.

## Honest weaknesses, if a judge asks

Better to have answers ready than to be caught out:

- **Intent detection is 77.8%.** Rule-based, not learned. Six of the eight
  failures return a defensible intent with a correct answer, and one is a
  labelling error in the dataset — which was deliberately not corrected,
  because editing the answer key to match the implementation would make the
  metric meaningless.
- **Windows only.** Active-window capture uses Win32 APIs.
- **Hindi/Hinglish is template-driven** and has not been reviewed by a native
  speaker.
- **No production validation.** No real Razorpay account was ever read or
  modified.
