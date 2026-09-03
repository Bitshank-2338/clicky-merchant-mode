# Pitch video

Independent hackathon prototype. Not an official Razorpay product.

`clicky-merchant-mode-demo.mp4` — 4m18s, 1920×1080, H.264 + AAC, ~6 MB.
Comfortably inside the Buildathon's five-minute limit.

## The point of this build script

Every rupee figure, every answer string and every metric in the video is pulled
from the **live pipeline and a real evaluation run at build time**. Nothing is
typed into a slide. If the settlement maths changes, or the evaluation score
moves, the video changes with it on the next build — it cannot quietly drift
into claiming something the software no longer does.

## Rebuild

```bash
python -m video.make_video
```

Frames only, no narration — for re-recording in your own voice:

```bash
python -m video.make_video --frames
```

## Files

| Path | What it is |
|---|---|
| `demo_script.py` | The scene list. Narration text lives here; content is fetched live. |
| `make_video.py` | Pillow frame renderer, edge-tts narration, ffmpeg assembly. |
| `build/` | Intermediates — frames, per-scene mp3s, cached evaluation summary. |
| `../docs/VIDEO_NARRATION.md` | Word-for-word script with real per-scene timings. |

## Requirements

`ffmpeg` on PATH (v9 tested), plus `pip install edge-tts pillow`. Narration
needs a network connection the first time; `build/audio/*.mp3` is then reused,
so delete that directory to force a re-render after editing narration.

## Editing

Change narration in `demo_script.py`, delete `build/audio/`, rebuild. The
builder prints each scene's measured duration and warns if the total crosses
five minutes.

Visual layouts live in `make_video.py`: `render_title`, `render_quote`,
`render_split`, `render_metrics`, `render_closing`. The dashboard mock the
split layout draws is `PAGE_ROWS` in the same file — note that these are
*drawn* rows, so if you change the seed data, update them to match.

## Known limits

- The visuals are a faithful **rendering**, not a screen recording of the real
  PyQt app. The content is real; the pixels are drawn. A short clip of the
  actual app would strengthen the submission — see
  `docs/SUBMISSION_CHECKLIST.md`.
- Narration is text-to-speech (`en-IN-NeerjaNeural`). Re-recording it in your
  own voice is recommended for an internship application.
