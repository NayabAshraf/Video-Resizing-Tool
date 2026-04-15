
"""
Video Resizer Tool (CPU-Optimized)
====================================
Resizes videos to social media aspect ratios using FFmpeg.
Videos are scaled to fit within the target ratio WITHOUT cropping.
Black padding is added to top/bottom or left/right as needed.

Audio fix: video and audio are split into separate stream nodes so
video filters never touch the audio — audio is copied as-is.

Requirements:
  pip install ffmpeg-python
  FFmpeg binary must be installed — see config.py
"""

import ffmpeg
import os
import time
from pathlib import Path

from config import (
    FFMPEG, FFPROBE,
    INPUT_VIDEO, OUTPUT_FOLDER,
    CRF, PRESET, OUTPUT_WIDTH,
    CLI_PRESETS,
)

os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def get_video_info(input_path: str):
    """Probe the video file and return (width, height, duration, has_audio)."""
    probe = ffmpeg.probe(input_path, cmd=FFPROBE)
    video_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "video"), None
    )
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
    if not video_stream:
        raise ValueError("No video stream found in file.")
    duration = float(probe["format"]["duration"])
    return int(video_stream["width"]), int(video_stream["height"]), duration, has_audio


def resize_video(
    input_path: str,
    output_path: str,
    ratio_w: int,
    ratio_h: int,
    output_width: int = OUTPUT_WIDTH,
):
    """
    Scale video to fit inside target ratio, pad remaining space with black.
    No cropping — the full frame is always preserved.

    AUDIO FIX: inp.video and inp.audio are accessed as separate nodes.
    Applying filters to inp.video only never touches the audio stream,
    so acodec='copy' works correctly and audio is never muted.
    """

    pipeline_start = time.perf_counter()

    # ── Stage 1: File validation ──────────────────
    t = time.perf_counter()
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    print(f"  [1] File validation        {time.perf_counter() - t:.3f}s")

    # ── Stage 2: Probe ────────────────────────────
    t = time.perf_counter()
    src_w, src_h, duration, has_audio = get_video_info(input_path)
    if src_w <= src_h:
        raise ValueError(
            f"Only landscape videos are accepted (width must exceed height). "
            f"Input is {src_w}x{src_h}."
        )
    print(f"  [2] Video probe (ffprobe)  {time.perf_counter() - t:.3f}s")
    print(f"\n  Source:  {src_w}x{src_h}  |  {duration:.1f}s  |  {file_size_mb:.1f} MB")
    print(f"  Audio:   {'Yes' if has_audio else 'No'}")

    # ── Stage 3: Canvas calculation ───────────────
    t = time.perf_counter()
    out_w = output_width + (output_width % 2)          # must be even for libx264
    out_h = int(out_w * ratio_h / ratio_w)
    out_h = out_h + (out_h % 2)
    print(f"  [3] Canvas calculation     {time.perf_counter() - t:.3f}s")
    print(f"  Canvas:  {out_w}x{out_h}  ({ratio_w}:{ratio_h})\n")

    # ── Stage 4: FFmpeg encode ────────────────────
    print("  [4] FFmpeg encoding...     ", end="", flush=True)
    t = time.perf_counter()

    inp = ffmpeg.input(input_path)

    # ── Video-only pipeline (filters applied to video stream only) ──
    video = (
        inp.video
        .filter("scale", out_w, out_h,
                force_original_aspect_ratio="decrease",
                flags="lanczos")
        .filter("scale", "trunc(iw/2)*2", "trunc(ih/2)*2")   # ensure even dims
        .filter("pad", out_w, out_h,
                x="(ow-iw)/2",
                y="(oh-ih)/2",
                color="black")
    )

    # ── Merge video + untouched audio into output ──
    if has_audio:
        out = ffmpeg.output(
            video,
            inp.audio,          # audio node — completely separate from video filters
            output_path,
            vcodec   = "libx264",
            crf      = CRF,
            preset   = PRESET,
            tune     = "fastdecode",
            threads  = 0,
            acodec   = "copy",  # copy audio bitstream as-is — no re-encode, no muting
            movflags = "+faststart",
        )
    else:
        out = ffmpeg.output(
            video,
            output_path,
            vcodec   = "libx264",
            crf      = CRF,
            preset   = PRESET,
            tune     = "fastdecode",
            threads  = 0,
            movflags = "+faststart",
        )

    out.overwrite_output().run(cmd=FFMPEG, quiet=True)

    encode_time = time.perf_counter() - t
    print(f"{encode_time:.3f}s")

    # ── Stage 5: Output verification ─────────────
    t = time.perf_counter()
    out_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [5] Output verification    {time.perf_counter() - t:.3f}s")

    # ── Summary ───────────────────────────────────
    total_time = time.perf_counter() - pipeline_start
    speed      = duration / total_time

    print(f"\n  ─────────────────────────────────────")
    print(f"  Total pipeline time:  {total_time:.2f}s")
    print(f"  Video duration:       {duration:.1f}s")
    print(f"  Speed:                {speed:.2f}x realtime")
    print(f"  Output size:          {out_size_mb:.1f} MB")
    print(f"  Saved to:             {output_path}")
    print(f"  ─────────────────────────────────────")


# ─────────────────────────────────────────────
# INTERACTIVE CLI
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("    🎬 Video Resizer — CPU Optimized")
    print("=" * 50)

    if not os.path.isfile(INPUT_VIDEO):
        print(f"\n❌ Input video not found:\n   {INPUT_VIDEO}")
        print("   Update INPUT_VIDEO in config.py.")
        return

    print(f"\n  Input:         {INPUT_VIDEO}")
    print(f"  Output folder: {os.path.abspath(OUTPUT_FOLDER)}")

    print("\nSelect output platform:")
    for key, val in CLI_PRESETS.items():
        r = val["ratio"]
        print(f"  [{key}] {val['name']:<35} ({r[0]}:{r[1]})")

    while True:
        choice = input("Enter choice (1-3): ").strip()
        if choice in CLI_PRESETS:
            preset = CLI_PRESETS[choice]
            break
        print("  ❌ Invalid choice.")

    ratio_w, ratio_h = preset["ratio"]
    print(f"  ✔ {preset['name']} ({ratio_w}:{ratio_h})")

    w_input = input(f"\nOutput width in pixels? [default: {OUTPUT_WIDTH}]: ").strip()
    output_width = int(w_input) if w_input.isdigit() else OUTPUT_WIDTH

    input_stem  = Path(INPUT_VIDEO).stem
    safe_name   = preset["name"].replace("/", "-").replace(" ", "_")
    output_path = os.path.join(OUTPUT_FOLDER, f"{input_stem}_{safe_name}.mp4")

    print(f"\n  Output: {output_path}")
    print("\n⏳ Pipeline starting...\n")

    resize_video(
        input_path   = INPUT_VIDEO,
        output_path  = output_path,
        ratio_w      = ratio_w,
        ratio_h      = ratio_h,
        output_width = output_width,
    )

    print("\n🎉 Done!")


if __name__ == "__main__":
    main()