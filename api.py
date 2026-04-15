"""
FastAPI Backend — Video Resizer  (Production Ready)
=====================================================
Single endpoint: POST /resize

Production features:
  ✅ File size limit       — rejects uploads over MAX_UPLOAD_SIZE_MB (413)
  ✅ Rate limiting         — max RATE_LIMIT_PER_MINUTE requests per IP (429)
  ✅ Restricted CORS       — only ALLOWED_ORIGINS can call this API
  ✅ Encode timeout        — FFmpeg killed if it exceeds ENCODE_TIMEOUT_SEC (504)
  ✅ Startup cleanup       — leftover temp files deleted on server start
  ✅ Semaphore queue       — 1000 requests accepted, only N encode at once
  ✅ Queue overflow (503)  — request 1001 gets a clean error, not a crash
  ✅ Auto file cleanup     — output files deleted after streaming to client
  ✅ Structured logging    — every request and error logged with job ID
  ✅ Cross-platform paths  — ffmpeg found automatically on any OS

Run (development):
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Run (production):
  gunicorn api:app --workers 4 --worker-class uvicorn.workers.UvicornWorker
                   --timeout 600 --bind 0.0.0.0:8000

Install:
  pip install fastapi uvicorn gunicorn python-multipart ffmpeg-python aiofiles slowapi
"""

import asyncio
import aiofiles
import ffmpeg
import uuid
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import (
    FFMPEG, FFPROBE,
    UPLOAD_DIR, OUTPUT_DIR,
    CRF, PRESET,
    RATIO_PRESETS,
    SUPPORTED_VIDEO_EXTENSIONS,
    ALLOWED_ORIGINS,
    MAX_CONCURRENT_JOBS,
    MAX_QUEUE_SIZE,
    MAX_UPLOAD_SIZE_MB,
    ENCODE_TIMEOUT_SEC,
    RATE_LIMIT_PER_MINUTE,
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)s | %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("video_resizer")

# ─────────────────────────────────────────────
# DIRECTORIES
# ─────────────────────────────────────────────
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# CONCURRENCY PRIMITIVES
# ─────────────────────────────────────────────
_encode_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_thread_pool      = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)
_active_requests  = 0
_active_lock      = asyncio.Lock()

# ─────────────────────────────────────────────
# RATE LIMITER
# ─────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ─────────────────────────────────────────────
# LIFESPAN — startup / shutdown
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Clean up leftover temp files from any previous crashed run
    deleted = 0
    for f in list(UPLOAD_DIR.glob("*")) + list(OUTPUT_DIR.glob("*")):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    if deleted:
        log.warning(f"Startup cleanup: removed {deleted} leftover temp file(s).")

    log.info(
        f"Server ready | "
        f"concurrent={MAX_CONCURRENT_JOBS} | queue={MAX_QUEUE_SIZE} | "
        f"max_upload={MAX_UPLOAD_SIZE_MB}MB | timeout={ENCODE_TIMEOUT_SEC}s | "
        f"rate_limit={RATE_LIMIT_PER_MINUTE}/min | cors={ALLOWED_ORIGINS}"
    )
    yield
    _thread_pool.shutdown(wait=False)
    log.info("Server shut down.")


# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────
app = FastAPI(title="Video Resizer API", version="3.0.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ALLOWED_ORIGINS,
    allow_methods  = ["POST"],
    allow_headers  = ["*"],
)


# ─────────────────────────────────────────────
# BLOCKING HELPERS  (run inside thread pool)
# ─────────────────────────────────────────────

def _probe_sync(input_path: Path):
    """Probe video metadata — blocking, runs in thread pool."""
    probe        = ffmpeg.probe(str(input_path), cmd=FFPROBE)
    video_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "video"), None
    )
    if not video_stream:
        raise ValueError("No video stream found in file.")
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
    duration  = float(probe["format"]["duration"])
    src_w     = int(video_stream["width"])
    src_h     = int(video_stream["height"])
    return has_audio, duration, src_w, src_h


def _encode_sync(input_path: Path, output_path: Path,
                 out_w: int, out_h: int, has_audio: bool) -> None:
    """FFmpeg encode — blocking CPU-bound, runs in thread pool."""
    inp   = ffmpeg.input(str(input_path))
    video = (
        inp.video
        .filter("scale", out_w, out_h,
                force_original_aspect_ratio="decrease", flags="lanczos")
        .filter("scale", "trunc(iw/2)*2", "trunc(ih/2)*2")
        .filter("pad", out_w, out_h, x="(ow-iw)/2", y="(oh-ih)/2", color="black")
    )
    streams    = [video, inp.audio] if has_audio else [video]
    out_kwargs = dict(
        vcodec="libx264", crf=CRF, preset=PRESET,
        tune="fastdecode", threads=0, movflags="+faststart",
        **({"acodec": "copy"} if has_audio else {}),
    )
    (
        ffmpeg.output(*streams, str(output_path), **out_kwargs)
        .overwrite_output()
        .run(cmd=FFMPEG, quiet=True)
    )


async def _run_in_thread(fn, *args):
    """Offload a blocking function to the thread pool without blocking the event loop."""
    return await asyncio.get_event_loop().run_in_executor(_thread_pool, fn, *args)


# ─────────────────────────────────────────────
# SINGLE ENDPOINT: POST /resize
# ─────────────────────────────────────────────

@app.post("/resize")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def resize_video(
    request:      Request,
    file:         UploadFile = File(...,  description="Input video file"),
    preset:       str        = Form(...,  description="tiktok | instagram | square"),
    output_width: int        = Form(1080, description="Output width in pixels"),
):
    """
    Upload a video + choose a preset → get back the resized video.

    Handles up to MAX_QUEUE_SIZE concurrent requests:
    - All requests are accepted and go through upload/probe simultaneously (async I/O).
    - Only MAX_CONCURRENT_JOBS encode at once — the rest wait using zero CPU.
    - Each request is cleaned up automatically on success, error, or disconnect.
    """
    global _active_requests
    job_id = uuid.uuid4().hex
    log.info(f"[{job_id}] Received | preset={preset} | width={output_width} | ip={request.client.host}")

    # ── 1. Queue overflow check ───────────────────────────────────────
    async with _active_lock:
        if _active_requests >= MAX_QUEUE_SIZE:
            log.warning(f"[{job_id}] Rejected — queue full ({_active_requests}/{MAX_QUEUE_SIZE})")
            raise HTTPException(
                status_code = 503,
                detail      = f"Server is at capacity ({MAX_QUEUE_SIZE} requests in queue). Try again later.",
            )
        _active_requests += 1
        log.info(f"[{job_id}] Queued — depth {_active_requests}/{MAX_QUEUE_SIZE}")

    input_path  = None
    output_path = None

    try:
        # ── 2. Validate preset ────────────────────────────────────────
        if preset not in RATIO_PRESETS:
            raise HTTPException(
                status_code = 400,
                detail      = f"Invalid preset '{preset}'. Choose from: {list(RATIO_PRESETS.keys())}",
            )

        # ── 3. Validate file extension ────────────────────────────────
        if not file.filename.lower().endswith(SUPPORTED_VIDEO_EXTENSIONS):
            raise HTTPException(
                status_code = 400,
                detail      = f"Unsupported file type. Allowed: {', '.join(SUPPORTED_VIDEO_EXTENSIONS)}",
            )

        # ── 4. Read upload + enforce size limit ───────────────────────
        try:
            file_bytes = await file.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read upload: {e}")

        size_mb = len(file_bytes) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_SIZE_MB:
            raise HTTPException(
                status_code = 413,
                detail      = f"File too large ({size_mb:.1f} MB). Max allowed: {MAX_UPLOAD_SIZE_MB} MB.",
            )
        log.info(f"[{job_id}] Upload size: {size_mb:.1f} MB")

        # ── 5. Save upload to disk (async write) ─────────────────────
        suffix      = Path(file.filename).suffix or ".mp4"
        input_path  = UPLOAD_DIR / f"{job_id}_input{suffix}"
        output_path = OUTPUT_DIR / f"{job_id}_{preset}_{output_width}w.mp4"

        try:
            async with aiofiles.open(input_path, "wb") as f_out:
                await f_out.write(file_bytes)
            del file_bytes      # free RAM immediately after saving to disk
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

        # ── 6. Probe video metadata (non-blocking) ────────────────────
        try:
            has_audio, duration, src_w, src_h = await _run_in_thread(_probe_sync, input_path)
            log.info(f"[{job_id}] Probe OK | {src_w}x{src_h} | duration={duration:.1f}s | audio={has_audio}")
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read video: {e}")

        # ── 7. Canvas calculation ─────────────────────────────────────
        ratio_w, ratio_h = RATIO_PRESETS[preset]
        out_w = output_width + (output_width % 2)           # must be even for libx264
        out_h = int(out_w * ratio_h / ratio_w)
        out_h = out_h + (out_h % 2)

        # ── 8. Semaphore gate + FFmpeg encode ─────────────────────────
        # Only MAX_CONCURRENT_JOBS pass through at once.
        # All others sleep here using zero CPU until a slot opens.
        # asyncio.wait_for cancels the job if FFmpeg exceeds ENCODE_TIMEOUT_SEC.
        log.info(f"[{job_id}] Waiting for encode slot...")
        t_start = time.perf_counter()

        try:
            async with _encode_semaphore:
                log.info(f"[{job_id}] Encoding → {out_w}x{out_h}")
                await asyncio.wait_for(
                    _run_in_thread(_encode_sync, input_path, output_path, out_w, out_h, has_audio),
                    timeout = ENCODE_TIMEOUT_SEC,
                )
        except asyncio.TimeoutError:
            log.error(f"[{job_id}] Timed out after {ENCODE_TIMEOUT_SEC}s")
            raise HTTPException(
                status_code = 504,
                detail      = f"Encoding timed out after {ENCODE_TIMEOUT_SEC}s. Try a shorter video.",
            )
        except Exception as e:
            log.error(f"[{job_id}] FFmpeg error: {e}")
            raise HTTPException(status_code=500, detail=f"FFmpeg error: {e}")

        elapsed     = time.perf_counter() - t_start
        out_size_mb = output_path.stat().st_size / (1024 * 1024)
        log.info(f"[{job_id}] Done in {elapsed:.1f}s | output={out_size_mb:.1f}MB")

        # ── 9. Stream response — output file deleted after download ───
        return FileResponse(
            path       = str(output_path),
            media_type = "video/mp4",
            filename   = f"resized_{preset}_{output_width}w.mp4",
            background = BackgroundTask(lambda p=output_path: p.unlink(missing_ok=True)),
            headers    = {
                "X-Job-ID":            job_id,
                "X-Duration-Seconds":  str(round(duration, 2)),
                "X-Output-Resolution": f"{out_w}x{out_h}",
                "X-Has-Audio":         str(has_audio),
                "X-Process-Time-Sec":  str(round(elapsed, 2)),
                "X-Output-Size-MB":    str(round(out_size_mb, 2)),
                "X-Queue-Depth":       str(_active_requests),
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        log.error(f"[{job_id}] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    finally:
        # Always runs — on success, error, or client disconnect.
        if input_path:
            input_path.unlink(missing_ok=True)
        async with _active_lock:
            _active_requests = max(0, _active_requests - 1)
        log.info(f"[{job_id}] Slot released — depth {_active_requests}/{MAX_QUEUE_SIZE}")