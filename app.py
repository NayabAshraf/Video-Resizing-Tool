


"""
Streamlit Frontend — Video Resizer  (Production Ready)
========================================================
Run with:
  streamlit run app.py

Requirements:
  pip install streamlit requests
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
import time
import base64

from config import (
    API_BASE_URL,
    PRESET_LABELS,
    RATIO_PRESETS,
    SUPPORTED_VIDEO_EXTENSIONS,
    OUTPUT_WIDTH,
    MAX_CONCURRENT_JOBS,
    MAX_QUEUE_SIZE,
    MAX_UPLOAD_SIZE_MB,
    RATE_LIMIT_PER_MINUTE,
)

# ─────────────────────────────────────────────
# PAGE SETUP
# ─────────────────────────────────────────────
st.set_page_config(
    page_title = "🎬 Video Resizer",
    page_icon  = "🎬",
    layout     = "centered",
)

st.title("🎬 Video Resizer")
st.caption(
    "Resize any video to social media aspect ratios — "
    "no cropping, black padding added automatically."
)

# ─────────────────────────────────────────────
# SIDEBAR — SERVER STATUS + LIVE QUEUE
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    api_url = st.text_input("API Base URL", value=API_BASE_URL)

    st.markdown("---")
    st.subheader("🟢 Server Status")

    api_online      = False
    active_requests = 0
    available_slots = MAX_QUEUE_SIZE
    concurrent_cap  = MAX_CONCURRENT_JOBS

    try:
        r = requests.post(f"{api_url}/resize", timeout=3)
        if r.status_code in (200, 400, 422):
            api_online = True
            st.success("✅ API is online")
        else:
            st.error(f"❌ API returned {r.status_code}")
    except Exception:
        st.error(
            "❌ Cannot reach API\n\n"
            "Start the server:\n"
            "```\nuvicorn api:app --port 8000\n```"
        )

    if api_online:
        st.caption(
            f"Concurrent encodes: **{concurrent_cap}** | "
            f"Queue cap: **{MAX_QUEUE_SIZE}** | "
            f"Rate limit: **{RATE_LIMIT_PER_MINUTE}/min**"
        )

    st.markdown("---")
    st.subheader("ℹ️ Limits")
    st.markdown(
        f"- Max upload: **{MAX_UPLOAD_SIZE_MB} MB**\n"
        f"- Rate limit: **{RATE_LIMIT_PER_MINUTE} requests/min**\n"
        f"- Queue cap: **{MAX_QUEUE_SIZE} jobs**"
    )

    st.markdown("---")
    st.subheader("Available Presets")
    for key, (rw, rh) in RATIO_PRESETS.items():
        st.markdown(f"- **{key}** → {rw}:{rh}")

# ─────────────────────────────────────────────
# MAIN FORM
# ─────────────────────────────────────────────
st.markdown("### 1. Upload your video")
st.caption(f"Max file size: **{MAX_UPLOAD_SIZE_MB} MB** | Formats: MP4, MOV, AVI, MKV, WEBM | **Landscape orientation required**")

supported_types = [ext.lstrip(".") for ext in SUPPORTED_VIDEO_EXTENSIONS]
uploaded_file = st.file_uploader(
    label = "Drop a video file here",
    type  = supported_types,
)

# ─────────────────────────────────────────────
# VALIDATION FLAGS
# ─────────────────────────────────────────────
is_valid_video   = False   # passes ALL checks
video_dimensions = None    # (width, height) tuple if landscape check passes

if uploaded_file is not None:

    # ── Check 1: File size ────────────────────────────────────────────
    file_bytes   = uploaded_file.getvalue()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    if file_size_mb > MAX_UPLOAD_SIZE_MB:
        st.error(
            f"❌ File is too large ({file_size_mb:.1f} MB). "
            f"Maximum allowed size is {MAX_UPLOAD_SIZE_MB} MB."
        )

    else:
        # ── Check 2: Landscape orientation via in-browser JS ─────────
        # Encode video as base64 so the browser can load it into a
        # <video> element and read its natural dimensions — all client-side,
        # no server round-trip needed.
        b64_video = base64.b64encode(file_bytes).decode("utf-8")
        mime_type = "video/mp4"   # browsers handle the rest regardless of container

        landscape_check_html = f"""
        <style>
            body {{ margin: 0; font-family: sans-serif; }}
            #result {{
                padding: 10px 14px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                display: none;
            }}
            #result.ok      {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
            #result.error   {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
            #result.loading {{ background: #fff3cd; color: #856404; border: 1px solid #ffeeba; display: block; }}
        </style>

        <div id="result" class="loading">⏳ Checking video orientation…</div>
        <video id="vid" style="display:none" muted preload="metadata"></video>

        <script>
            const vid = document.getElementById('vid');
            const res = document.getElementById('result');

            // Load video from base64 data URI
            vid.src = 'data:{mime_type};base64,{b64_video}';

            vid.addEventListener('loadedmetadata', function() {{
                const w = vid.videoWidth;
                const h = vid.videoHeight;

                if (w > h) {{
                    res.className  = 'ok';
                    res.textContent = '✅ Landscape video detected — ' + w + ' × ' + h + ' px';
                }} else {{
                    res.className  = 'error';
                    res.textContent = (
                        '❌ Portrait / square video detected (' + w + ' × ' + h + ' px). '
                        + 'Please upload a landscape video (width must be greater than height).'
                    );
                }}
                res.style.display = 'block';
            }});

            vid.addEventListener('error', function() {{
                res.className  = 'error';
                res.textContent = '⚠️ Could not read video metadata in browser — '
                                + 'server will validate on submission.';
                res.style.display = 'block';
            }});
        </script>
        """

        # Render the JS checker; height sized to just fit the result banner
        components.html(landscape_check_html, height=60, scrolling=False)

        # ── Python-side landscape check using ffmpeg.probe ────────────
        # This is the authoritative check that gates the Resize button.
        # We probe only the uploaded bytes — no server API call yet.
        try:
            import ffmpeg
            import tempfile, os
            from config import FFPROBE

            # Write bytes to a temp file so ffprobe can read them
            suffix = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            probe        = ffmpeg.probe(tmp_path, cmd=FFPROBE)
            video_stream = next(
                (s for s in probe["streams"] if s["codec_type"] == "video"), None
            )
            os.unlink(tmp_path)   # clean up immediately

            if video_stream:
                vid_w = int(video_stream["width"])
                vid_h = int(video_stream["height"])
                video_dimensions = (vid_w, vid_h)

                if vid_w > vid_h:
                    is_valid_video = True   # ✅ passes all checks
                else:
                    # Show a clear Streamlit-native error so there's no ambiguity
                    st.error(
                        f"🚫 **Portrait or square video detected** ({vid_w} × {vid_h} px).\n\n"
                        f"This tool only accepts **landscape** videos "
                        f"(width must be greater than height).\n\n"
                        f"Please rotate your video or upload a different clip."
                    )
            else:
                st.warning("⚠️ Could not detect video dimensions. Proceeding — server will validate.")
                is_valid_video = True   # let server be the final judge

        except Exception as probe_err:
            st.warning(
                f"⚠️ Local orientation check failed (`{probe_err}`). "
                "The server will validate on submission."
            )
            is_valid_video = True   # fallback: don't block if probe unavailable

# ─────────────────────────────────────────────
# OUTPUT SETTINGS
# ─────────────────────────────────────────────
st.markdown("### 2. Choose output settings")

col1, col2 = st.columns(2)
with col1:
    preset_key = st.selectbox(
        "Platform / Aspect Ratio",
        options     = list(PRESET_LABELS.keys()),
        format_func = lambda k: PRESET_LABELS[k],
    )
with col2:
    output_width = st.select_slider(
        "Output Width (px)",
        options = [720, 1080, 1280, 1440, 1920],
        value   = OUTPUT_WIDTH,
        help    = "Height is calculated automatically from the aspect ratio.",
    )

rw, rh = RATIO_PRESETS[preset_key]
ow = output_width + (output_width % 2)
oh = int(ow * rh / rw)
oh = oh + (oh % 2)
st.info(f"📐 Output resolution: **{ow} × {oh}** px  |  Ratio: **{rw}:{rh}**")

# ─────────────────────────────────────────────
# PROCESS
# ─────────────────────────────────────────────
st.markdown("### 3. Process")

# Disable the button if no file or if orientation check failed
button_disabled = (uploaded_file is None) or (not is_valid_video)

if button_disabled:
    st.button("🚀 Resize Video", disabled=True)
    if uploaded_file is None:
        st.caption("Upload a video above to enable processing.")
    elif not is_valid_video:
        st.caption("⬆️ Please upload a landscape video to continue.")

else:
    if st.button("🚀 Resize Video", type="primary"):

        progress_bar = st.progress(0, text="Uploading video...")
        status_area  = st.empty()

        try:
            progress_bar.progress(10, text="Uploading video...")
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "video/mp4")}
            data  = {"preset": preset_key, "output_width": output_width}

            t_start = time.time()
            progress_bar.progress(20, text="Waiting in queue / Encoding...")

            response = requests.post(
                f"{api_url}/resize",
                files   = files,
                data    = data,
                timeout = 1800,
                stream  = True,
            )

            progress_bar.progress(80, text="Receiving processed video...")

            if response.status_code == 200:
                elapsed      = time.time() - t_start
                headers      = response.headers
                job_id       = headers.get("X-Job-ID",            "?")
                duration_s   = headers.get("X-Duration-Seconds",  "?")
                resolution   = headers.get("X-Output-Resolution", "?")
                has_audio    = headers.get("X-Has-Audio",          "?")
                proc_time    = headers.get("X-Process-Time-Sec",  f"{elapsed:.1f}")
                size_mb      = headers.get("X-Output-Size-MB",     "?")
                output_bytes = response.content

                progress_bar.progress(100, text="✅ Done!")
                status_area.success(f"✅ Done!  Job `{job_id}` | Total time: {elapsed:.1f}s")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Duration",    f"{duration_s}s")
                m2.metric("Resolution",  resolution)
                m3.metric("Audio",       "✅" if has_audio == "True" else "❌")
                m4.metric("Encode Time", f"{proc_time}s")
                st.metric("Output Size", f"{size_mb} MB")

                st.markdown("### 4. Download")
                st.download_button(
                    label     = "⬇️ Download Resized Video",
                    data      = output_bytes,
                    file_name = f"resized_{preset_key}_{output_width}w.mp4",
                    mime      = "video/mp4",
                    type      = "primary",
                )
                with st.expander("▶️ Preview output video", expanded=True):
                    st.video(output_bytes)

            elif response.status_code == 429:
                progress_bar.empty()
                st.error(
                    f"❌ Rate limit reached. "
                    f"Max {RATE_LIMIT_PER_MINUTE} uploads per minute. Please wait and try again."
                )
            elif response.status_code == 413:
                progress_bar.empty()
                st.error(f"❌ File too large. Maximum allowed size is {MAX_UPLOAD_SIZE_MB} MB.")
            elif response.status_code == 503:
                progress_bar.empty()
                st.error("❌ Server is at full capacity. Please wait a moment and try again.")
            elif response.status_code == 504:
                progress_bar.empty()
                st.error("❌ Encoding timed out. Try a shorter video or smaller output width.")
            elif response.status_code == 400 and "landscape" in response.text.lower():
                progress_bar.empty()
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                st.error(
                    f"🚫 Server rejected the video — portrait orientation detected.\n\n{detail}"
                )
            else:
                progress_bar.empty()
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                st.error(f"❌ API Error {response.status_code}: {detail}")

        except requests.exceptions.ConnectionError:
            progress_bar.empty()
            st.error("❌ Could not connect to the API. Is the server running?")
        except requests.exceptions.Timeout:
            progress_bar.empty()
            st.error("❌ Request timed out. The queue may be very long — try again later.")
        except Exception as e:
            progress_bar.empty()
            st.error(f"❌ Unexpected error: {e}")

# ─────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:grey; font-size:0.85em;'>"
    "Powered by FFmpeg · FastAPI · Streamlit"
    "</div>",
    unsafe_allow_html=True,
)