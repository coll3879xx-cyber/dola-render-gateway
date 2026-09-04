# Dola Render Gateway

A high-performance session coordinator and OpenAI-compatible video generation API service.

Provides automated browser session isolation, task queue distribution, extended duration handling, and an intuitive web management dashboard.

---

## 🌟 Key Capabilities

1. **OpenAI-Compatible Video API**:
   - `POST /v1/videos/generations`: Submit generation tasks with prompt, aspect ratio, duration (`10s`, `15s`, `30s`), and reference images.
   - `GET /v1/videos/<id>`: Poll task lifecycle (`queued` -> `processing` -> `completed` / `failed`).
   - High-speed MP4 streaming and static asset delivery.
2. **Extended Duration & High-Definition Media Export**:
   - Integrated browser automation profile for managing extended duration options.
   - Direct original quality stream extraction and processing.
3. **Multi-Account Browser Pool**:
   - Manages multiple persistent browser profiles in `accounts/`.
   - Automatic concurrency management, mutual exclusion, and session rotation.
   - Built-in verification handling.
4. **Admin Web Dashboard**:
   - Real-time dashboard at `/web` to monitor generation trends, success rate, account statuses, task queues, and API key management.

---

## 📁 Repository Structure

```
dola-render-gateway/
├── server.py              # FastAPI server (OpenAI-compatible video API & admin routes)
├── browser_pool.py        # Account pool concurrency manager and task scheduler
├── browser.py             # Playwright persistent context launcher
├── video_worker_ui.py     # UI automation worker with verification handler
├── video_worker.py        # Protocol worker and status polling
├── store.py               # SQLite task persistence and API key storage
├── dola_client.py         # API client communication module
├── media.py               # Reference media processor
├── config.py              # Configuration & environment variables
├── add_account.py         # Automated account profile setup
├── web/
│   └── index.html         # Single-page admin management dashboard
└── extensions/
    └── dola30/            # Chromium extension profile
```

---

## 🚀 Quick Start

### 1. Requirements
* Python 3.11+
* Chrome / Chromium browser
* Proxy with JP/KR egress

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
# Set your proxy configuration
export DOLA_PROXY="http://127.0.0.1:7890"

# Set API key for client authentication (optional, empty = dev mode)
export DOLA_API_KEYS="sk-your-secret-key"

# Concurrency limits
export DOLA_MAX_CONCURRENCY=3
```

### 4. Start Server
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```
Open **http://127.0.0.1:8000/web** to access the Admin Dashboard.

---

## 📜 License
For educational and internal testing purposes.
