# Loupe

An agent that shows its reasoning. Most assistants hide what happened between your question
and the answer: which tools ran, what came back, why the next step was chosen. Loupe records
each of those steps and puts them on screen.

A persisted chat backed by the Claude API, with a visible tool trace. `fetch_url` reads
web pages. `run_python` executes Python in a Docker container with no network and no
access to the host filesystem. It is offered only when Docker is available and its
image can be prepared. Set `ENABLE_CODE_EXECUTION=false` to turn it off.

## Stack

- Backend: FastAPI (Python), Anthropic Claude API
- Frontend: Next.js, TypeScript, Tailwind CSS
- Database: Postgres via Supabase

## Setup

### 1. Database

Create a Supabase project, then run the SQL files in `backend/migrations/` in numerical
order in the Supabase SQL editor.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000.

## Optional semantic recall

Semantic recall combines local `voyageai/voyage-4-nano` embeddings with BM25, using
256 dimensions and mean pooling. It costs about 1.1GB of libraries plus about 704MB of
model weights. Without the libraries and cached weights, recall is BM25 only.

From `backend/`, install the optional dependencies and explicitly pre-fetch the model:

```bash
.venv/bin/pip install -r requirements-embeddings.txt
.venv/bin/huggingface-cli download voyageai/voyage-4-nano
```

Restart the backend after fetching. Startup warms the model; requests never download it.
Transformers must stay below version 5. The model requires `trust_remote_code=True`.
After applying migration `0008_memory_embeddings.sql`, embed existing facts with:

```bash
.venv/bin/python -m scripts.backfill_embeddings
```

The backfill only updates facts with null embeddings and can be run again safely.
New facts receive embeddings when available. Development dependencies in
`requirements-dev.txt` include the optional libraries; tests never download weights.

## Checks

```bash
cd backend  && .venv/bin/ruff check . && .venv/bin/mypy app && .venv/bin/pytest
cd frontend && npm run lint && npm run typecheck && npm run test
```
