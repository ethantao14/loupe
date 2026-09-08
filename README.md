# Loupe

An agent that shows its reasoning. Most assistants hide what happened between your question
and the answer: which tools ran, what came back, why the next step was chosen. Loupe records
each of those steps and puts them on screen.

A persisted chat backed by the Claude API, with a visible tool trace. Tools include
`fetch_url` for web pages and `run_python` for Python in a resource-limited subprocess.
Python runs in a temporary directory without inherited credentials; this is not filesystem
or network isolation. It requires working POSIX resource limits (finite address-space
limits are unavailable on macOS).

## Stack

- Backend: FastAPI (Python), Anthropic Claude API
- Frontend: Next.js, TypeScript, Tailwind CSS
- Database: Postgres via Supabase

## Setup

### 1. Database

Create a Supabase project, then run `backend/migrations/0001_create_messages.sql` in the
Supabase SQL editor.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
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

## Checks

```bash
cd backend  && .venv/bin/ruff check . && .venv/bin/mypy app && .venv/bin/pytest
cd frontend && npm run lint && npm run typecheck && npm run test
```
