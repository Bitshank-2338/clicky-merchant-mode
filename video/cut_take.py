"""
Cut a raw screen recording down to its usable parts.

Takes a list of keep-segments and produces one clean MP4. Re-encodes rather
than stream-copying, because a stream copy can only cut on keyframes — which
on a 60fps screen capture can be seconds away from where you actually wanted
the cut, and would drag material back in that was meant to be removed.

    python -m video.cut_take --plan video/build/cut/plan.json

Plan format:

    {
      "source": "video/raw/take1.mp4",
      "output": "video/clicky-demo-cut.mp4",
      "keep": [
        {"start": 29.5, "end": 38.5, "why": "settlements page, Clicky panel up"},
        {"start": 57.0, "end": 293.0, "why": "main demo"}
      ]
    }

Every segment carries a `why` so the edit is auditable: anyone can read the
plan and see what was removed and on what grounds.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Segment:
    start: float
    end: float
    why: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def extract(source: Path, seg: Segment, dest: Path, crf: int = 20,
            fps: Optional[int] = 30) -> None:
    """Cut one segment. `-ss` after `-i` is slower but frame-accurate."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(source),
        "-ss", f"{seg.start:.3f}", "-to", f"{seg.end:.3f}",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        # Reset timestamps so the pieces concatenate without gaps.
        "-avoid_negative_ts", "make_zero",
    ]
    if fps:
        cmd += ["-r", str(fps)]
    cmd.append(str(dest))
    subprocess.run(cmd, check=True)


def concat(parts: list[Path], dest: Path) -> None:
    listing = dest.parent / "concat.txt"
    listing.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(dest)],
        check=True,
    )


def run(plan_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found on PATH")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    source = REPO / plan["source"]
    output = REPO / plan["output"]
    segments = [Segment(float(s["start"]), float(s["end"]), s.get("why", ""))
                for s in plan["keep"]]

    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    if not segments:
        raise SystemExit("plan keeps nothing")

    total = probe_duration(source)
    for seg in segments:
        if seg.duration <= 0:
            raise SystemExit(f"segment {seg.start}-{seg.end} is empty")
        if seg.end > total + 0.5:
            raise SystemExit(f"segment ends at {seg.end}s, past the {total:.1f}s source")

    work = output.parent / "build" / "cut" / "parts"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    kept = sum(s.duration for s in segments)
    print(f"source : {source.name}  ({total:.1f}s)")
    print(f"keeping: {kept:.1f}s across {len(segments)} segment(s) "
          f"— removing {total - kept:.1f}s\n")

    parts: list[Path] = []
    for i, seg in enumerate(segments):
        part = work / f"part{i:02d}.mp4"
        print(f"  [{i}] {seg.start:7.1f}s → {seg.end:7.1f}s "
              f"({seg.duration:5.1f}s)  {seg.why}")
        extract(source, seg, part)
        parts.append(part)

    concat(parts, output)
    final = probe_duration(output)
    print(f"\nwrote {output}")
    print(f"duration: {int(final // 60)}m {final % 60:04.1f}s")
    return output


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Cut a raw take down to a plan.")
    ap.add_argument("--plan", required=True, help="path to the JSON edit plan")
    args = ap.parse_args()
    run(Path(args.plan))


if __name__ == "__main__":
    main()
