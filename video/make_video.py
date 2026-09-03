"""
Render the pitch video.

Builds an MP4 from the scenes in `demo_script.py`:

    scenes -> narration (edge-tts) -> key frames (Pillow) -> ffmpeg -> demo.mp4

Design choice: each scene renders a handful of *key frames* held for a slice of
its narration, rather than thousands of animation frames. A pitch video for a
tool like this is read, not watched — holding a legible frame while the
narration explains it beats motion for its own sake, and it renders in seconds.

Usage:
    python -m video.make_video              # full build
    python -m video.make_video --frames     # frames only, no audio (fast preview)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from video.demo_script import Scene, build_scenes

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "video" / "build"
FRAMES = BUILD / "frames"
AUDIO = BUILD / "audio"
OUT = REPO / "video" / "clicky-merchant-mode-demo.mp4"

W, H = 1920, 1080
FPS = 30

VOICE = "en-IN-NeerjaNeural"   # Indian English, matches the audience
RATE = "+2%"                   # brisk enough for the 5-minute cap, still clear

# Palette — deliberately close to the product's own.
BG = (10, 22, 40)
BG_SOFT = (16, 32, 56)
CARD = (255, 255, 255)
CARD_DARK = (20, 38, 66)
NAVY = (12, 36, 81)
BLUE = (51, 149, 255)
AMBER = (245, 166, 35)
GREEN = (46, 174, 116)
RED = (214, 69, 65)
TEXT = (238, 244, 252)
MUTED = (150, 170, 196)
INK = (22, 32, 48)
INK_MUTED = (104, 122, 148)


# ── Fonts ─────────────────────────────────────────────────────────────────────

def _font_path(*candidates: str) -> Optional[str]:
    roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts")]
    for name in candidates:
        for root in roots:
            p = root / name
            if p.exists():
                return str(p)
    return None


_LATIN = _font_path("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")
_LATIN_BOLD = _font_path("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")
# Devanagari — without this, Hindi answers render as boxes.
_DEVA = _font_path("Nirmala.ttf", "mangal.ttf", "NotoSansDevanagari-Regular.ttf")

_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False, deva: bool = False) -> ImageFont.FreeTypeFont:
    path = (_DEVA if deva and _DEVA else (_LATIN_BOLD if bold else _LATIN))
    key = (path or "default", size)
    if key not in _cache:
        _cache[key] = (ImageFont.truetype(path, size) if path
                       else ImageFont.load_default())
    return _cache[key]


def _has_devanagari(text: str) -> bool:
    return any("\u0900" <= c <= "\u097f" for c in text)


def pick(size: int, text: str, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Choose a font that can actually draw `text`."""
    return font(size, bold=bold, deva=_has_devanagari(text))


# ── Drawing helpers ───────────────────────────────────────────────────────────


def rounded(d: ImageDraw.ImageDraw, box, radius: int, fill=None, outline=None,
            width: int = 1) -> None:
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
         max_w: int) -> list[str]:
    """Greedy wrap measured against the real font."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_para(d: ImageDraw.ImageDraw, xy, text: str, size: int, max_w: int,
              fill=TEXT, bold: bool = False, leading: float = 1.45,
              max_lines: Optional[int] = None) -> int:
    x, y = xy
    f = pick(size, text, bold)
    lines = wrap(d, text, f, max_w)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,") + " …"
    for line in lines:
        d.text((x, y), line, font=f, fill=fill)
        y += int(size * leading)
    return y


def frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # Subtle vertical lift so the flat navy does not read as dead.
    for i in range(H):
        t = i / H
        d.line([(0, i), (W, i)],
               fill=(int(BG[0] + (BG_SOFT[0] - BG[0]) * t),
                     int(BG[1] + (BG_SOFT[1] - BG[1]) * t),
                     int(BG[2] + (BG_SOFT[2] - BG[2]) * t)))
    return img, d


def chrome(d: ImageDraw.ImageDraw, scene: Scene) -> None:
    """Persistent header and footer."""
    d.text((72, 54), "CLICKY MERCHANT MODE", font=font(22, bold=True), fill=BLUE)
    if scene.badge:
        f = font(20, bold=True)
        tw = d.textlength(scene.badge, font=f)
        colour = RED if scene.live_mode else AMBER
        rounded(d, (W - 72 - tw - 36, 46, W - 72, 90), 22,
                fill=None, outline=colour, width=2)
        d.text((W - 72 - tw - 18, 57), scene.badge, font=f, fill=colour)
    d.line([(72, H - 74), (W - 72, H - 74)], fill=(30, 52, 84), width=1)
    d.text((72, H - 56), "Independent hackathon prototype · not an official "
                         "Razorpay product · all demo data is synthetic",
           font=font(17), fill=MUTED)


# ── Dashboard mock ────────────────────────────────────────────────────────────

NAV = [("Home", "nav.home"), ("Payments", "nav.payments"),
       ("Settlements", "nav.settlements"), ("Refunds", "nav.refunds"),
       ("Payment Links", "nav.payment_links"), ("Reports", "nav.reports")]

PAGE_ROWS: dict[str, list[tuple[str, str, str]]] = {
    # page -> [(label, value, target_id)]
    "settlements": [
        ("Settlement period", "01 Sept 2026", "settlement.period"),
        ("Gross amount", "₹10,000", "settlement.gross_amount"),
        ("Razorpay fees", "₹200", "settlement.fees"),
        ("Tax on fees", "₹36", "settlement.tax"),
        ("Refunds", "₹500", "settlement.refunds"),
        ("Net settlement", "₹9,264", "settlement.net_amount"),
        ("UTR", "UTRDEMO0001", "settlement.utr"),
    ],
    "settlements_live": [
        ("Settlement period", "02 Sept 2026", "settlement.period"),
        ("Gross amount", "₹47,320", "settlement.gross_amount"),
        ("Razorpay fees", "₹946", "settlement.fees"),
        ("Tax on fees", "₹170", "settlement.tax"),
        ("Net settlement", "₹46,204", "settlement.net_amount"),
        ("UTR", "HDFC9931", "settlement.utr"),
    ],
    "settlements_empty": [],
    "payments": [
        ("Date range", "02 Sept 2026", "payments.date_filter"),
        ("Status", "Failed", "payments.status_filter"),
        ("Apply filters", "", "payments.apply_filter"),
        ("pay_DEMOF001 · Kavita R.", "₹1,200 · failed", "payments.table"),
        ("pay_DEMOF002 · Suresh N.", "₹899 · failed", "payments.table"),
        ("Failure reason", "not enough balance", "payments.error_reason"),
    ],
    "payment_links": [
        ("Amount", "", "link.amount"),
        ("Description", "", "link.description"),
        ("Expire by", "", "link.expiry"),
        ("Customer name", "", "link.customer_name"),
        ("Phone number", "", "link.customer_contact"),
        ("Preview link", "", "link.preview"),
        ("Create payment link", "", "link.create_button"),
    ],
    "refunds": [
        ("Payments", "", "nav.payments"),
        ("Payment ID", "pay_DEMO0102", "payments.table"),
        ("Refund ID", "rfnd_DEMO102", "refunds.table"),
        ("Refund type", "partial", "refunds.type"),
    ],
}


def draw_dashboard(img: Image.Image, d: ImageDraw.ImageDraw, box,
                   page: str, highlight: Optional[str], live: bool) -> None:
    x0, y0, x1, y1 = box
    rounded(d, box, 18, fill=CARD)

    # Title bar
    d.rectangle((x0, y0, x1, y0 + 54), fill=(244, 247, 251))
    label = ("dashboard.razorpay.com/app/settlements" if live
             else "127.0.0.1:8756/dashboard  ·  DEMO DATA")
    d.text((x0 + 24, y0 + 17), label, font=font(19, bold=True),
           fill=RED if live else INK_MUTED)

    # Sidebar
    sb_w = 232
    d.rectangle((x0, y0 + 54, x0 + sb_w, y1), fill=NAVY)
    active = {"settlements": "Settlements", "settlements_live": "Settlements",
              "settlements_empty": "Settlements", "payments": "Payments",
              "payment_links": "Payment Links", "refunds": "Refunds"}.get(page, "Home")
    ny = y0 + 84
    for name, tid in NAV:
        is_active = name == active
        if is_active:
            d.rectangle((x0, ny - 10, x0 + sb_w, ny + 34), fill=(24, 58, 122))
            d.rectangle((x0, ny - 10, x0 + 4, ny + 34), fill=BLUE)
        hot = highlight == tid
        if hot:
            rounded(d, (x0 + 10, ny - 10, x0 + sb_w - 10, ny + 34), 8,
                    outline=AMBER, width=3)
        d.text((x0 + 28, ny), name, font=font(21, bold=is_active),
               fill=(255, 255, 255) if is_active or hot else (176, 198, 232))
        ny += 52

    # Content
    cx = x0 + sb_w + 40
    heading = {"payments": "Payments", "payment_links": "Payment Links",
               "refunds": "Refunds"}.get(page, "Settlements")
    d.text((cx, y0 + 92), heading, font=font(38, bold=True), fill=INK)

    rows = PAGE_ROWS.get(page, [])
    if not rows:
        d.text((cx, y0 + 190), "No transactions yet", font=font(24), fill=INK_MUTED)
        d.text((cx, y0 + 228), "Nothing to explain — and nothing invented.",
               font=font(19), fill=INK_MUTED)
        return

    ry = y0 + 156
    row_h = 52
    for label_text, value, tid in rows:
        hot = highlight == tid
        if hot:
            rounded(d, (cx - 14, ry - 10, x1 - 34, ry + row_h - 18), 9,
                    fill=(255, 248, 232))
            rounded(d, (cx - 14, ry - 10, x1 - 34, ry + row_h - 18), 9,
                    outline=AMBER, width=3)
        emphasise = "net" in tid or tid.endswith("create_button")
        d.text((cx, ry), label_text, font=font(21, bold=emphasise or hot),
               fill=INK if (emphasise or hot) else (72, 88, 112))
        if value:
            f = font(21, bold=emphasise or hot)
            d.text((x1 - 58 - d.textlength(value, font=f), ry), value, font=f,
                   fill=INK if (emphasise or hot) else (72, 88, 112))
        ry += row_h


# ── Clicky panel ──────────────────────────────────────────────────────────────


def draw_panel(d: ImageDraw.ImageDraw, box, scene: Scene,
               step_index: Optional[int]) -> None:
    x0, y0, x1, y1 = box
    rounded(d, box, 18, fill=CARD_DARK, outline=(38, 66, 108), width=2)
    inner = x1 - x0 - 64
    y = y0 + 30

    # Header + privacy strip
    d.ellipse((x0 + 32, y + 6, x0 + 50, y + 24), fill=BLUE)
    d.text((x0 + 62, y + 2), "Clicky", font=font(24, bold=True), fill=TEXT)
    d.ellipse((x1 - 210, y + 9, x1 - 198, y + 21), fill=GREEN)
    d.text((x1 - 186, y + 3), "Privacy ON", font=font(17, bold=True), fill=GREEN)
    y += 46
    d.text((x0 + 32, y), "Active window only · screenshots saved: 0",
           font=font(16), fill=MUTED)
    y += 40

    # Merchant's question
    if scene.utterance:
        f = pick(20, scene.utterance)
        lines = wrap(d, scene.utterance, f, inner - 40)
        bh = len(lines) * 29 + 26
        rounded(d, (x0 + 32, y, x1 - 32, y + bh), 12, fill=(30, 56, 96))
        yy = y + 13
        for line in lines:
            d.text((x0 + 50, yy), line, font=f, fill=(206, 226, 250))
            yy += 29
        y += bh + 24

    # Answer
    if scene.answer:
        y = draw_para(d, (x0 + 32, y), scene.answer, 21, inner, fill=TEXT,
                      leading=1.42, max_lines=7)
        y += 18

    # Steps
    if scene.steps and step_index is not None:
        d.text((x0 + 32, y), "STEPS", font=font(15, bold=True), fill=MUTED)
        y += 28
        for i, (title, _why) in enumerate(scene.steps[:6]):
            done, current = i < step_index, i == step_index
            colour = GREEN if done else (AMBER if current else (58, 84, 122))
            d.ellipse((x0 + 34, y + 5, x0 + 50, y + 21), fill=colour)
            if done:
                d.line([(x0 + 38, y + 13), (x0 + 41, y + 17),
                        (x0 + 47, y + 9)], fill=CARD_DARK, width=2)
            f = pick(18, title, bold=current)
            for j, line in enumerate(wrap(d, title, f, inner - 40)[:2]):
                d.text((x0 + 62, y + j * 23), line, font=f,
                       fill=TEXT if current else (MUTED if not done else (150, 200, 176)))
            y += 23 * min(2, max(1, len(wrap(d, title, f, inner - 40)))) + 12
        y += 6

    # Footer note
    if y < y1 - 70:
        d.text((x0 + 32, y1 - 52),
               "Deterministic answer · no model required",
               font=font(16), fill=MUTED)


# ── Layouts ───────────────────────────────────────────────────────────────────


def render_split(scene: Scene, highlight: Optional[str],
                 step_index: Optional[int]) -> Image.Image:
    img, d = frame()
    chrome(d, scene)
    d.text((72, 116), scene.heading, font=pick(40, scene.heading, bold=True),
           fill=TEXT)
    top = 196
    page = scene.page
    if scene.live_mode:
        page = "settlements_live"
    elif scene.scenario == "empty_state":
        page = "settlements_empty"
    draw_dashboard(img, d, (72, top, 1112, H - 116), page, highlight,
                   scene.live_mode)
    draw_panel(d, (1152, top, W - 72, H - 116), scene, step_index)
    return img


def render_title(scene: Scene) -> Image.Image:
    img, d = frame()
    d.text((W // 2, 300), "CLICKY", font=font(28, bold=True), fill=BLUE,
           anchor="mm")
    d.text((W // 2, 400), scene.heading, font=font(96, bold=True), fill=TEXT,
           anchor="mm")
    d.text((W // 2, 490), scene.subheading, font=font(38), fill=MUTED,
           anchor="mm")
    if scene.badge:
        f = font(22, bold=True)
        tw = d.textlength(scene.badge, font=f)
        rounded(d, (W // 2 - tw // 2 - 26, 566, W // 2 + tw // 2 + 26, 618), 26,
                outline=AMBER, width=2)
        d.text((W // 2, 592), scene.badge, font=f, fill=AMBER, anchor="mm")
    d.text((W // 2, 760), "₹10,000 collected      →      ₹9,264 in the bank",
           font=font(40, bold=True), fill=TEXT, anchor="mm")
    d.text((W // 2, 826), "Nothing on the screen explains the difference.",
           font=font(26), fill=MUTED, anchor="mm")
    d.text((W // 2, H - 60), "Independent hackathon prototype · not an official "
                             "Razorpay product", font=font(17), fill=MUTED,
           anchor="mm")
    return img


def render_quote(scene: Scene, reveal: int) -> Image.Image:
    img, d = frame()
    chrome(d, scene)
    d.text((120, 210), scene.heading, font=pick(56, scene.heading, bold=True),
           fill=TEXT)
    y = 360
    for i, bullet in enumerate(scene.bullets):
        shown = i < reveal
        colour = TEXT if shown else (44, 68, 102)
        d.ellipse((120, y + 14, 136, y + 30), fill=BLUE if shown else (40, 62, 96))
        f = pick(30, bullet)
        for j, line in enumerate(wrap(d, bullet, f, W - 340)):
            d.text((172, y + j * 42), line, font=f, fill=colour)
        y += 42 * max(1, len(wrap(d, bullet, f, W - 340))) + 30
    return img


def render_metrics(scene: Scene, reveal: int) -> Image.Image:
    img, d = frame()
    chrome(d, scene)
    d.text((120, 190), scene.heading, font=font(56, bold=True), fill=TEXT)
    d.text((120, 268), scene.subheading, font=font(26), fill=MUTED)
    cols, cw, ch = 4, 400, 190
    x_start, y_start = 120, 360
    for i, (label, value) in enumerate(scene.metrics):
        if i >= reveal:
            continue
        cx = x_start + (i % cols) * (cw + 24)
        cy = y_start + (i // cols) * (ch + 24)
        good = value in ("100%", "0", "0%") or value.startswith("100")
        rounded(d, (cx, cy, cx + cw, cy + ch), 14, fill=(18, 36, 62),
                outline=(38, 68, 110), width=2)
        d.text((cx + 28, cy + 34), value, font=font(58, bold=True),
               fill=GREEN if good else BLUE)
        for j, line in enumerate(wrap(d, label, font(21), cw - 56)[:2]):
            d.text((cx + 28, cy + 116 + j * 26), line, font=font(21), fill=MUTED)
    d.text((120, H - 116), "Reproduce with:  python -m merchant.evaluation.runner",
           font=font(22, bold=True), fill=AMBER)
    return img


def render_closing(scene: Scene) -> Image.Image:
    img, d = frame()
    d.text((W // 2, 300), scene.heading, font=font(72, bold=True), fill=TEXT,
           anchor="mm")
    y = 430
    for line in scene.subheading.split("\n"):
        d.text((W // 2, y), line, font=font(34), fill=(196, 216, 240), anchor="mm")
        y += 58
    d.text((W // 2, 720), "github.com/Bitshank-2338/clicky-merchant-mode",
           font=font(30, bold=True), fill=BLUE, anchor="mm")
    d.text((W // 2, 790), "285 tests · 36 evaluated tasks · 0 hallucinations · "
                          "0 privacy violations", font=font(24), fill=MUTED,
           anchor="mm")
    d.text((W // 2, H - 80), scene.badge, font=font(18), fill=MUTED, anchor="mm")
    return img


# ── Frame planning ────────────────────────────────────────────────────────────


@dataclass
class Shot:
    image: Image.Image
    weight: float = 1.0     # relative share of the scene's duration


def plan(scene: Scene) -> list[Shot]:
    if scene.layout == "title":
        return [Shot(render_title(scene))]
    if scene.layout == "closing":
        return [Shot(render_closing(scene))]
    if scene.layout == "quote":
        n = len(scene.bullets)
        return [Shot(render_quote(scene, i + 1)) for i in range(n)] or \
               [Shot(render_quote(scene, 0))]
    if scene.layout == "metrics":
        n = len(scene.metrics)
        return [Shot(render_metrics(scene, i + 1)) for i in range(n)]

    # split: walk the highlights, then the steps
    shots: list[Shot] = []
    highlights = [h for h in scene.highlights][:6]
    if not highlights:
        return [Shot(render_split(scene, None, None), 1.0)]
    # Open on the whole screen, then focus each element in turn.
    shots.append(Shot(render_split(scene, None, 0 if scene.steps else None), 0.9))
    for i, target in enumerate(highlights):
        step_index = min(i, len(scene.steps) - 1) if scene.steps else None
        shots.append(Shot(render_split(scene, target, step_index), 1.0))
    return shots


# ── Narration ─────────────────────────────────────────────────────────────────


async def _tts(text: str, path: Path) -> None:
    import edge_tts

    await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path))


def narrate(scenes: Sequence[Scene]) -> list[Path]:
    AUDIO.mkdir(parents=True, exist_ok=True)
    paths = []
    for scene in scenes:
        path = AUDIO / f"{scene.key}.mp3"
        if not path.exists():
            print(f"  narrating {scene.key} …")
            asyncio.run(_tts(scene.narration, path))
        paths.append(path)
    return paths


def duration_of(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ── Build ─────────────────────────────────────────────────────────────────────


def build(with_audio: bool = True) -> Path:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found on PATH — install it and retry.")

    scenes = build_scenes()
    print(f"Rendering {len(scenes)} scenes …")

    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    audio_paths = narrate(scenes) if with_audio else []
    durations = ([duration_of(p) for p in audio_paths] if with_audio
                 else [6.0] * len(scenes))

    concat_lines: list[str] = []
    index = 0
    for scene, secs in zip(scenes, durations):
        shots = plan(scene)
        total_weight = sum(s.weight for s in shots)
        # A little air after the narration stops, so it never feels clipped.
        secs = secs + 0.35
        print(f"  {scene.key:12s} {len(shots)} shots  {secs:5.1f}s")
        for shot in shots:
            path = FRAMES / f"f{index:04d}.png"
            shot.image.save(path)
            concat_lines.append(f"file '{path.as_posix()}'")
            concat_lines.append(f"duration {secs * shot.weight / total_weight:.3f}")
            index += 1
    # The concat demuxer needs the final image repeated to honour its duration.
    concat_lines.append(f"file '{(FRAMES / f'f{index - 1:04d}.png').as_posix()}'")

    concat_file = BUILD / "frames.txt"
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

    silent = BUILD / "video_only.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-preset", "medium",
         str(silent)],
        check=True,
    )

    if not with_audio:
        shutil.move(str(silent), str(OUT))
        print(f"\nWrote {OUT} (no audio)")
        return OUT

    list_file = BUILD / "audio.txt"
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in audio_paths), encoding="utf-8")
    voice = BUILD / "voice.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c:a", "aac", "-b:a", "192k", str(voice)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(voice),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT)],
        check=True,
    )

    total = duration_of(OUT)
    print(f"\nWrote {OUT}")
    print(f"Duration: {int(total // 60)}m {total % 60:04.1f}s")
    if total > 300:
        print("WARNING: over the 5-minute limit — trim narration in demo_script.py")
    return OUT


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Build the Merchant Mode pitch video.")
    ap.add_argument("--frames", action="store_true",
                    help="render frames without narration (fast preview)")
    args = ap.parse_args()
    build(with_audio=not args.frames)


if __name__ == "__main__":
    main()
