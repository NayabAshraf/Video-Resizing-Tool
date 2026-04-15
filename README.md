A high-performance video resizing web application built with FastAPI + FFmpeg + Streamlit.

This tool allows users to upload videos and resize them into social media aspect ratios 
(TikTok, Instagram, Square) without cropping, using smart scaling and padding.


FEATURES:
Backend (FastAPI):
- High-performance async API
- Handles up to 1000 queued requests
- Concurrent encoding using semaphore control
- Rate limiting (per IP)
- Upload size restriction
- Timeout protection for FFmpeg
- Auto cleanup of temporary files
- Structured logging with Job IDs
- Cross-platform support
Frontend (Streamlit):
- Simple and clean UI
- Drag & drop video upload
- Live video orientation check (Landscape only)
- Real-time progress tracking
- Video preview and download
- Server status and queue info


HOW IT WORKS:
Pipeline:
1. User uploads video
2. File validation (size, format, orientation)
3. Video metadata extracted using FFprobe
4. Output resolution calculated
5. FFmpeg resizes video:
   - Keeps full frame (no cropping)
   - Adds black padding
6. Output streamed back to user
7. File automatically deleted after download

TECH STACK:
Backend: FastAPI
- Frontend: Streamlit
- Video Processing: FFmpeg
- Concurrency: AsyncIO + ThreadPoolExecutor
- Rate Limiting: SlowAPI


PROJECT STRUCTURE:
project/

│-- api.py          (FastAPI backend)
│-- app.py          (Streamlit frontend)
│-- config.py       (Central configuration)
│-- main.py         (CLI tool)

│-- uploads/        (temporary input files)
│-- outputs/        (processed videos)

⚙️ INSTALLATION:
1. Clone Repository:
   git clone https://github.com/NayabAshraf/Video-Resizing-Tool.git
   cd video-resizer

2. Install Dependencies:
   pip install -r requirements.txt

3. Install FFmpeg:
   Download from: https://ffmpeg.org/download.html
   Update config.py:
   FFMPEG  = r"C:\ffmpeg\bin\ffmpeg.exe"
   FFPROBE = r"C:\ffmpeg\bin\ffprobe.exe"


RUN THE PROJECT:
Start Backend:
   uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Start Frontend:
   streamlit run app.py
