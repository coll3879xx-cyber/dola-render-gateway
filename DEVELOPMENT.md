# Dola Pool - Architecture & Technical Documentation

This document outlines the protocol architecture, reverse-engineering findings, and operational mechanisms implemented in `dola-pool`.

---

## 1. Core Architecture

The system operates across three tiers:
1. **API Tier (`server.py`)**: FastAPI application exposing standard OpenAI video endpoints (`/v1/videos/generations`, `/v1/videos/<id>`) and web dashboard routes (`/web`, `/api/admin/*`).
2. **Pool Management Tier (`browser_pool.py`)**: Manages persistent browser profiles in `accounts/`, controlling task concurrency, account locking, and daily quota rotations.
3. **Execution Tier (`video_worker_ui.py`, `video_worker.py`)**:
   - **UI Automation Mode**: Automates browser interactions, authenticates via real browser cookies, injects prompts, and solves slider captchas via OpenCV template matching.
   - **Protocol Mode**: Sends structured SSE requests to `/chat/completion` and polls `/im/chain/single` for video rendering progress.

---

## 2. 30-Second Video Unlock Mechanism

Dola natively presents limited duration buttons in standard chat sessions. To enable **15s** and **30s** durations:
- The included Chromium extension (`extensions/dola30/`) intercepts network requests via the `chrome.debugger` API.
- Intercepts `/samantha/skill/pack` and replaces the response with `dola-skill-pack-response.json`, unlocking the extended duration parameters.
- Intercepts `/alice/slot/action_bar_v3/get_item_conf` to display 30s selection buttons in the client action bar.

---

## 3. Watermark Removal & Master 1080P Extraction

- Preview players on Dola display lower-resolution video streams with watermarks.
- The true master 1080P unwatermarked video is returned in the API response under `creation_block.creations[].video.video_model`.
- Parsing `video_model.video_list.*.main_url` reveals Base64-encoded URLs with query parameter `lr=unwatermarked`.
- The worker decodes this stream URL and downloads the unwatermarked 1080P MP4 directly to `downloads/`.

---

## 4. Captcha Handling (Slider Puzzle Solver)

When ByteDance triggers risk control verification:
- A `bdcaptcha.html` iframe appears containing background and puzzle piece images.
- `gap.py` applies OpenCV Canny edge detection and template matching (`cv2.matchTemplate`) on the alpha channel of the puzzle piece against the background.
- `video_worker_ui.py` calculates the displacement and moves the slider using human-like mouse trajectories (smootherstep interpolation with slight overshoot and vertical jitter).
