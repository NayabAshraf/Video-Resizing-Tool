
"""
config.py — Centralized Configuration
=======================================
All project-wide settings live here.
Edit this file directly to change any setting.
"""

import os
import shutil
import multiprocessing
from pathlib import Path

# ─────────────────────────────────────────────
# FFMPEG BINARY PATHS
# ─────────────────────────────────────────────
# Automatically finds ffmpeg on your system PATH.
# On Windows: set full paths manually e.g. r"C:\ffmpeg\bin\ffmpeg.exe"
FFMPEG  = r"C:\ffmpeg\bin\ffmpeg.exe"
FFPROBE = r"C:\ffmpeg\bin\ffprobe.exe"

# ─────────────────────────────────────────────
# DIRECTORIES
# ─────────────────────────────────────────────
INPUT_VIDEO   = "input/video.mp4"   # used by CLI (main.py)
OUTPUT_FOLDER = Path("output")      # used by CLI (main.py)
UPLOAD_DIR    = Path("uploads")     # used by API (api.py)
OUTPUT_DIR    = Path("outputs")     # used by API (api.py)

# ─────────────────────────────────────────────
# CONCURRENCY
# ─────────────────────────────────────────────
# How many FFmpeg jobs run at the SAME TIME
# Rule: cpu_count // 2  (e.g. 4 on 8-core machine)
MAX_CONCURRENT_JOBS: int = max(1, multiprocessing.cpu_count() // 2)

# How many total requests can be queued at once
# Requests beyond this get a 503 "Server busy" error
MAX_QUEUE_SIZE: int = 1000

# ─────────────────────────────────────────────
# LIMITS & TIMEOUTS
# ─────────────────────────────────────────────
MAX_UPLOAD_SIZE_MB:    int = 500   # reject uploads larger than this
ENCODE_TIMEOUT_SEC:    int = 300   # kill FFmpeg if it runs longer than this
RATE_LIMIT_PER_MINUTE: int = 5     # max requests per IP per minute

# ─────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────
# List of frontend origins allowed to call the API
# Change to your actual domain in production e.g. ["https://yourdomain.com"]
ALLOWED_ORIGINS: list[str] = ["http://localhost:8501"]

# ─────────────────────────────────────────────
# ENCODING SETTINGS
# ─────────────────────────────────────────────
CRF:          int = 26            # Quality: 18 (best) – 28 (fastest)
PRESET:       str = "ultrafast"   # encoding speed preset
OUTPUT_WIDTH: int = 1080          # default output width in pixels

# ─────────────────────────────────────────────
# ASPECT RATIO PRESETS
# ─────────────────────────────────────────────
CLI_PRESETS = {
    "1": {"name": "TikTok / Instagram Reels",    "ratio": (9, 16)},
    "2": {"name": "Instagram Feed",               "ratio": (4, 5)},
    "3": {"name": "Square (Facebook/Instagram)",  "ratio": (1, 1)},
}

RATIO_PRESETS = {
    "tiktok":    (9, 16),
    "instagram": (4, 5),
    "square":    (1, 1),
}


# ─────────────────────────────────────────────
# STREAMLIT / FRONTEND SETTINGS
# ─────────────────────────────────────────────
API_BASE_URL = "http://localhost:8000"

PRESET_LABELS = {
    "tiktok":    "📱 TikTok / Instagram Reels  (9:16)",
    "instagram": "🟫 Instagram Feed            (4:5)",
    "square":    "⬛ Square — Facebook/Instagram (1:1)",
}

SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm")