# Loupe

Loupe is an agent with a visible reasoning trace beneath each reply. It records the model's
plans, tool calls, results and recalled memories so you can inspect how it reached an answer.

## What it does

- Persists conversations and their traces, with replies and steps streamed live.
- Reads web pages with `fetch_url` and runs Python in Docker with `run_python`.
- Stores facts with `remember`, recalls them in later turns, and lets you delete them.
- Records tool failures and blocks identical failed calls from running again in the same turn.
- Holds separate conversations, with a sidebar to switch between, rename and delete them.

<!-- demo gif goes here -->
*A screen recording is coming.*

## How it works

The Next.js frontend uses TypeScript and Tailwind CSS. A FastAPI backend calls the Anthropic
Claude API and stores conversations, messages, trace steps and memories in Supabase Postgres.

The agent loop in `backend/app/agent.py` is hand written rather than delegated to an SDK
helper. A loop hidden inside a library has no steps for Loupe to record, which would gut the
trace. Owning the loop makes each model response and tool execution a place to record a step.

The recorded step kinds are:

- `thinking`: model reasoning or interim text before a tool call.
- `tool_call`: the tool name and its input.
- `tool_result`: output from a successful tool call.
- `tool_error`: output from a failed tool call.
- `tool_repeat`: an identical failed call blocked from running again in the same turn.
- `answer`: the final response.
- `memory`: recalled facts, their scores, the rankers used and any fallback reason.

A turn streams over server-sent events (SSE), so the reply and its trace grow live. Completed
messages and steps are persisted together, and the frontend displays the trace beneath the
reply.

## Retrieval

Memory recall ranks stored facts against the latest user message. Hand written BM25 in
`backend/app/ranking.py` is fused with optional local `voyage-4-nano` embeddings via reciprocal
rank fusion. Without the model or stored vectors, recall uses BM25. When no terms match and
dense recall is unavailable, it falls back to recent facts. Selected facts become context in
the next model request, and a `memory` step records what was recalled.

The fusion has two rules that matter:

- A zero BM25 score does not vote. Its tie order is just insertion order, so letting it vote
  buries correct dense hits.
- Each fact votes once per ranker. Duplicates would otherwise outrank better placed unique
  facts.

Measured over a fixed set of 13 queries against 12 stored facts, counting how often the
correct fact was retrieved: keyword only 5/13, dense only 12/13, naive fusion 7/13, and the
shipped fusion 12/13. Naive fusion scoring worse than dense alone is what motivated the first
rule above.

This is not a benchmark. Eleven of the twelve facts were written alongside the code they test,
and a self authored set flatters the approach that produced it. Treat it as evidence that the
approach works and that the fusion rules are necessary, not as a score.

## Sandboxing

`run_python` executes model written Python inside a Docker container with no network, no host
filesystem access, a read only root, a tmpfs workdir, and capped memory, CPU and process count.
Memory and swap are capped together, because Docker otherwise grants an equal amount of swap
and the cap is really double.

If Docker is unavailable, the tool is withheld from the model entirely rather than falling
back to something weaker. A failed container launch never falls back to host execution.
Set `ENABLE_CODE_EXECUTION=false` to turn the tool off.

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

### Optional semantic recall

Semantic recall uses local `voyageai/voyage-4-nano` embeddings with 256 dimensions and mean
pooling. Without the optional libraries and cached weights, recall is BM25 only.

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

The six gates are backend lint, type checking and tests, plus frontend lint, type checking
and tests. The backend suite contains 275 tests. CI runs it with `-rs` so a skipped test cannot
be mistaken for a passing one.

```bash
cd backend  && .venv/bin/ruff check . && .venv/bin/mypy app && .venv/bin/pytest
cd frontend && npm run lint && npm run typecheck && npm run test
```

## Known limits

- Fetch timeouts bound inactivity, not total duration, so a server trickling headers can hold
  a request worker.
- Stored facts are injected into later prompts, so a prompt injected page could plant one.
  The trace shows the `remember` call and facts can be deleted, but nothing blocks planting.

## License

[MIT](LICENSE), copyright 2026 Ethan Tao.
