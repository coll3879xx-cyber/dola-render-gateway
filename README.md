# Dola Pool

**Dola Pool** is a high-performance account pool manager and OpenAI-compatible video generation API server for ByteDance's **Dola AI (Seedance 2.0 / 2.5)**.

It provides automated browser session isolation, 30-second video duration unlock via Chromium debugger interception, real-time unwatermarked 1080P video extraction, and an intuitive web management dashboard.

---

## 🌟 Key Features

1. **OpenAI-Compatible Video API**:
   - `POST /v1/videos/generations`: Submit generation tasks with prompt, ratio, duration (`10s`, `15s`, `30s`), and reference images.
   - `GET /v1/videos/<id>`: Poll task lifecycle (`queued` -> `processing` -> `completed` / `failed`).
   - Static video hosting at `/videos/<filename>` with direct high-speed MP4 streaming.
2. **30-Second Duration & Master 1080P Unlock**:
   - Includes the unpacked Chromium debugger extension (`extensions/dola30/`) that unlocks 15s and 30s video lengths.
   - Automatically extracts clean, unwatermarked 1080P ByteDance master video streams.
3. **Multi-Account Browser Pool**:
   - Manages multiple isolated persistent Chromium profiles in `accounts/`.
   - Automatic concurrency management, mutual exclusion, and intelligent rotation when daily credit quotas are reached (2 videos / day / free account).
   - Built-in OpenCV slider puzzle captcha solver.
4. **Admin Web Dashboard**:
   - Real-time dashboard at `/web` to monitor generation trends, success rate, account statuses, task queues, and API key management.

---

## 📁 Repository Structure

```
dola-pool/
├── server.py              # FastAPI server (OpenAI-compatible video API & admin routes)
├── browser_pool.py        # Account pool concurrency manager and task scheduler
├── browser.py             # Playwright persistent context launcher
├── video_worker_ui.py     # UI automation worker with captcha solver
├── video_worker.py        # Direct protocol worker and status polling
├── store.py               # SQLite task persistence and API key storage
├── dola_client.py         # Reverse-engineered Dola communication module
├── media.py               # SSRF-protected reference image downloader
├── config.py              # Configuration & environment variables
├── add_account.py         # Automated Google OAuth login profile generator
├── web/
│   └── index.html         # Single-page admin management dashboard
└── extensions/
    └── dola30/            # Chromium extension for 30s unlock & unwatermarked video
```

---

## 🚀 Quick Start

### 1. Requirements
* Python 3.11+
* Chrome / Chromium browser
* Proxy with Japan/Korea egress (dola.com requires JP/KR egress IPs)

### 2. Setup Environment
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure
```bash
# Set your Japan/Korea proxy (Required for dola.com access)
export DOLA_PROXY="http://127.0.0.1:7890"

# Set API key for client authentication (optional, empty = dev mode)
export DOLA_API_KEYS="sk-your-secret-key"

# Concurrency limits
export DOLA_MAX_CONCURRENCY=3
```

### 4. Add Accounts
```bash
# Add an account using Google credentials (headful browser login)
python add_account.py acc1 "your_email@gmail.com----password----totp_secret"
```

### 5. Start Server
```bash
# Start FastAPI server
uvicorn server:app --host 0.0.0.0 --port 8000
```
Open **http://127.0.0.1:8000/web** to access the Admin Dashboard.

---

## 📡 API Usage

### Create Video Task
```bash
curl -X POST http://127.0.0.1:8000/v1/videos/generations \
  -H "Authorization: Bearer sk-your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "seedance-2.5",
    "prompt": "A cinematic shot of a neon cyberpunk city in rain",
    "size": "720x1280",
    "duration": 30
  }'
```
**Response:**
```json
{
  "id": "video_abc123",
  "status": "queued",
  "model": "seedance-2.5",
  "prompt": "A cinematic shot of a neon cyberpunk city in rain"
}
```

### Query Task Status
```bash
curl http://127.0.0.1:8000/v1/videos/video_abc123 \
  -H "Authorization: Bearer sk-your-secret-key"
```
**Response (When completed):**
```json
{
  "id": "video_abc123",
  "status": "completed",
  "video_url": "http://127.0.0.1:8000/videos/video_abc123.mp4"
}
```

---

## 📜 License & Notes
This project is for educational and research purposes. Video models and service APIs belong to their respective owners.
