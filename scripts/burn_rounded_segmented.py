#!/usr/bin/env python
"""Segment-based rounded-background subtitle burn-in.

Reuses ``render_subtitle_image()`` so the visual result is pixel-identical to the
GUI's "圆角背景" mode, but replaces the per-batch full re-encode with
time-segment encoding + concat.  A 4.7 h video with 1394 cues therefore gets
encoded *once* instead of 28 times.

Usage:
    python scripts/burn_rounded_segmented.py <video> <srt> <output> [options]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.entities import SubtitleLayoutEnum
from videocaptioner.core.subtitle.rounded_renderer import (
    CHUNK_SIZE,
    _get_video_info,
    _plan_chunks,
    render_subtitle_image,
)
from videocaptioner.core.subtitle.styles import RoundedBgStyle

REFERENCE_HEIGHT = 720


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_style(style_dict: dict, height: int) -> RoundedBgStyle:
    style = RoundedBgStyle(**style_dict)
    scale = height / REFERENCE_HEIGHT
    if scale != 1.0:
        style = replace(
            style,
            font_size=int(style.font_size * scale),
            corner_radius=int(style.corner_radius * scale),
            padding_h=int(style.padding_h * scale),
            padding_v=int(style.padding_v * scale),
            margin_bottom=int(style.margin_bottom * scale),
            line_spacing=int(style.line_spacing * scale),
            letter_spacing=int(style.letter_spacing * scale),
        )
    return style


def run(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0),
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed:\n" + " ".join(cmd) + "\n\n" + (result.stderr or "")[-4000:]
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("srt")
    ap.add_argument("output")
    ap.add_argument("--chunk", type=int, default=CHUNK_SIZE, help="cues per chunk")
    ap.add_argument("--crf", type=int, default=21)
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--audio-bitrate", default="192k")
    ap.add_argument("--workdir", default="")
    ap.add_argument("--limit-seconds", type=float, default=0.0, help="preview only")
    ap.add_argument("--font-size", type=int, default=30)
    ap.add_argument("--margin-bottom", type=int, default=40)
    ap.add_argument("--bg-color", default="#000000e5")
    ap.add_argument("--text-color", default="#ffffff")
    ap.add_argument("--corner-radius", type=int, default=14)
    ap.add_argument("--padding-h", type=int, default=18)
    ap.add_argument("--padding-v", type=int, default=16)
    ap.add_argument("--line-spacing", type=int, default=10)
    ap.add_argument("--letter-spacing", type=int, default=2)
    ap.add_argument("--font-name", default="Noto Sans SC")
    args = ap.parse_args()

    video = Path(args.video)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    width, height, duration = _get_video_info(str(video))
    log(f"video {width}x{height}  duration {duration:.1f}s ({duration / 3600:.2f}h)")

    style = build_style(
        {
            "font_name": args.font_name,
            "font_size": args.font_size,
            "bg_color": args.bg_color,
            "text_color": args.text_color,
            "corner_radius": args.corner_radius,
            "padding_h": args.padding_h,
            "padding_v": args.padding_v,
            "margin_bottom": args.margin_bottom,
            "line_spacing": args.line_spacing,
            "letter_spacing": args.letter_spacing,
            "layout": SubtitleLayoutEnum.ONLY_ORIGINAL,
        },
        height,
    )

    asr = ASRData.from_subtitle_file(str(args.srt))
    segments = asr.segments
    log(f"cues {len(segments)}  font_size {style.font_size}  margin_bottom {style.margin_bottom}")

    if args.limit_seconds > 0:
        duration = min(duration, args.limit_seconds)
        segments = [s for s in segments if s.start_time / 1000.0 < duration]
        asr.segments = segments
        log(f"preview mode: {duration:.1f}s, {len(segments)} cues")

    workdir = Path(args.workdir) if args.workdir else out.parent / ".burn_chunks"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    png_dir = workdir / "png"
    png_dir.mkdir()

    # Step 1: render every cue to a transparent PNG (thin slice of total runtime)
    log("rendering subtitle PNGs ...")
    t0 = time.time()
    png_paths = []
    for i, seg in enumerate(segments):
        img = render_subtitle_image(seg.text or "", "", width, height, style)
        p = png_dir / f"sub_{i:06d}.png"
        img.save(p, "PNG")
        png_paths.append(p)
        if (i + 1) % 250 == 0:
            log(f"  png {i + 1}/{len(segments)}")
    log(f"png done in {time.time() - t0:.1f}s")

    # Step 2: encode contiguous chunks, overlaying only that chunk's cues
    chunks = _plan_chunks(segments, duration, args.chunk)
    log(f"encoding {len(chunks)} chunks (single pass overall)")

    chunk_files = []
    total_start = time.time()
    for ci, (c_start, c_end, events) in enumerate(chunks):
        span = c_end - c_start
        if span <= 0.02:
            continue

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{c_start:.3f}", "-t", f"{span:.3f}", "-i", str(video),
        ]
        for _, _, seg_idx in events:
            cmd.extend(["-i", str(png_paths[seg_idx])])

        filters = []
        for local, (ev_start, ev_end, _) in enumerate(events):
            s = max(0.0, ev_start - c_start)
            e = min(span, ev_end - c_start)
            if e <= s:
                continue
            prev = f"[v{local - 1}]" if local > 0 else "[0:v]"
            outl = f"[v{local}]"
            filters.append(
                f"{prev}[{local + 1}:v]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'{outl}"
            )
        if not filters:
            filters = ["[0:v]null[v0]"]

        chunk_file = workdir / f"chunk_{ci:04d}.mp4"
        cmd.extend(
            [
                "-filter_complex", ";".join(filters),
                "-map", f"[v{len(filters) - 1}]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", args.preset,
                "-crf", str(args.crf),
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", args.audio_bitrate,
                "-ar", "48000",
                "-ac", "2",
                str(chunk_file),
            ]
        )
        run(cmd)
        chunk_files.append(chunk_file)

        done = (ci + 1) / len(chunks)
        elapsed = time.time() - total_start
        eta = elapsed / done * (1 - done) if done > 0 else 0
        log(
            f"  chunk {ci + 1}/{len(chunks)}  [{c_start:.0f}s-{c_end:.0f}s]  "
            f"{done * 100:.0f}%  eta {eta / 60:.0f}min"
        )

    # Step 3: concat without re-encoding
    log("concatenating ...")
    list_file = workdir / "list.txt"
    list_file.write_text(
        "\n".join(f"file '{f.as_posix()}'" for f in chunk_files), encoding="utf-8"
    )
    run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart",
            str(out),
        ]
    )

    log(f"done -> {out}  ({out.stat().st_size / 1024 ** 3:.2f} GB, {time.time() - total_start:.0f}s)")
    if not args.limit_seconds:
        shutil.rmtree(workdir, ignore_errors=True)
        log("temp cleaned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
