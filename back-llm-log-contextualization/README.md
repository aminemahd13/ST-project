# back-llm-log-contextualization

Production-oriented FastAPI backend for asynchronous PDF incident contextualization.

## What This Backend Now Provides

- Asynchronous job pipeline (`collector -> preprocessing -> incident -> analysis`)
- Persistent SQL storage for job metadata, stage events, and artifacts
- Durable file storage for uploaded PDFs
- Job API:
  - `POST /api/analyze` returns `{ job_id, status_url }`
  - `GET /api/jobs/{job_id}` returns job status, stages, and final analysis
- Strict LLM-driven analysis stage (Hugging Face API or local Ollama) without deterministic summary fallback
- Lightweight RAG retrieval seeded from historical PDFs (configurable directory)
- Request tracing (`x-request-id`), basic rate limiting, optional API key auth
- Prometheus-style metrics endpoint at `GET /metrics`

## Environment Variables

Copy `.env.example` to `.env` and update values.

Important keys:

- `GRID_APP_DATABASE_URL`
  - Production default: `postgresql+psycopg://...`
  - Dev fallback can use SQLite async URL (`sqlite+aiosqlite:///./grid_log.db`)
- `GRID_APP_STORAGE_DIR` for uploaded files and RAG index
- `GRID_APP_RAG_SEED_DIR` for historical PDF indexing
- `GRID_APP_LLM_PROVIDER` (`auto`, `huggingface`, `ollama`)
- `GRID_APP_HF_TOKEN` and `GRID_APP_HF_MODEL` for Hugging Face hosted inference (free-tier friendly)
- `GRID_APP_OLLAMA_BASE_URL` and `GRID_APP_OLLAMA_MODEL` for local Ollama enrichment
- `GRID_APP_API_KEY` optional API protection

## LLM Provider Options

Use `.env` to choose your provider:

- `GRID_APP_LLM_PROVIDER=auto`
  - Prefer Hugging Face when `GRID_APP_HF_TOKEN` is set.
  - Otherwise use Ollama if configured.
- `GRID_APP_LLM_PROVIDER=huggingface`
  - Requires `GRID_APP_HF_TOKEN`.
  - Default model: `katanemo/Arch-Router-1.5B:hf-inference`.
  - Good option when you cannot run Ollama locally.
  - If token is missing, `POST /api/analyze` now returns `503 llm_misconfigured` immediately.
- `GRID_APP_LLM_PROVIDER=ollama`
  - Requires local Ollama server (default: `http://localhost:11434`) and a pulled model.
  - Default model is `llama3.2:1b` for reliable laptop inference.

Example Ollama setup:

```bash
ollama serve
ollama pull llama3.2:1b
```

## Quick Start (Docker Compose)

From `back-llm-log-contextualization/`:

```bash
docker compose up --build
```

This starts:
- `db` (PostgreSQL)
- `api` (FastAPI backend on `http://localhost:8000`)

If you want local Ollama in Docker too, run:

```bash
docker compose --profile ollama up --build
```

That additionally starts:
- `ollama` (local model server on `http://localhost:11434`)
- `ollama-pull` (one-shot model download for `GRID_APP_OLLAMA_MODEL`)

Notes:
- With the default command (no profile), no local model download is required.
- With `--profile ollama`, first startup may take several minutes because the Ollama model is downloaded.
- Ollama model data is persisted in Docker volume `ollama_data`, so next starts are faster.
- Docker uses `GRID_APP_DATABASE_URL_DOCKER` and `GRID_APP_OLLAMA_BASE_URL_DOCKER` so local `.env` values (like `localhost`) do not break in-container networking.

## Quick Start (Local Python)

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Workflow

1. `POST /api/analyze` (multipart form `file`)
2. Poll `GET /api/jobs/{job_id}` until status becomes `completed`, `partial`, or `failed`
3. Render `analysis` markdown plus `stages` timeline in frontend

Note:
- If LLM generation fails or returns invalid JSON, the `analysis` stage is marked `failed` and diagnostics are exposed in stage payloads.
