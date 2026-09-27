# Loupe

Loupe is an agent with a visible reasoning trace beneath each reply. It records the model's
plans, tool calls, results and recalled memories so you can inspect how it reached an answer.

## What it does

- Persists conversations and their traces, with replies and steps streamed live.
- Reads web pages with `fetch_url` and runs Python in Docker with `run_python`.
- Stores facts with `remember`, recalls them in later turns, and lets you delete them.
- Records tool failures and blocks identical failed calls from running again in the same turn.
- Gives each browser its own private space for conversations and remembered facts.
- Holds separate conversations, with a sidebar to switch between, rename and delete them.
- Opens with a narrated replay of a real turn and suggests prompts for a first question.

**[Try the live demo](https://loupe-red.vercel.app)**. It opens with a guided tour of a
recorded turn, then lets you send a few live messages of your own.

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

## Guided tour

A first visit plays a real recorded turn in the live interface: it recalls a stored fact,
fetches a Wikipedia page and answers from it. Playback pauses at each new step with a caption
in that step's colour, and the sidebar and memory panel stay dimmed until they matter. The
replay is static data, so the tour works even when the backend is down. "Take the tour" in the
header plays it again, and an empty chat offers suggested prompts plus two uncaptioned replays,
one running Python and one recovering from a failed fetch.

The replays in `frontend/app/demo/replays.json` are recorded from a running backend rather than
written by hand. Captions are keyed by step kind, so re-recording never breaks them:

```bash
cd backend && .venv/bin/python -m scripts.record_replay ../frontend/app/demo/replays.json
```

## Setup

### 1. Database

Create a Supabase project, then run the SQL files in `backend/migrations/` in numerical
order in the Supabase SQL editor.

Migration `0009_visitor_isolation.sql` prints an `Existing data visitor ID` notice.
To claim pre-existing conversations and facts, save that UUID in your browser console
on the frontend's origin, then reload:

```js
localStorage.setItem("loupe.visitorId", "UUID_FROM_MIGRATION_NOTICE");
```

Keep this ID private: it grants access to that browser's space without a login.
If browser storage is unavailable, the visitor ID is kept only for the page's lifetime.

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
After applying all migrations, embed a visitor's existing facts using their visitor ID:

```bash
.venv/bin/python -m scripts.backfill_embeddings --visitor-id YOUR_VISITOR_UUID
```

The backfill only updates facts with null embeddings and can be run again safely.
New facts receive embeddings when available. Development dependencies in
`requirements-dev.txt` include the optional libraries; tests never download weights.

## Demo limits

Only live messages use the paid API. Replays and the guided tour are static and free.
Apply `0010_usage_limits.sql` and set these optional backend environment variables:

| Variable | Effect |
| --- | --- |
| `DAILY_MESSAGES_PER_VISITOR` | Daily cap per browser visitor ID, for example `10`. |
| `DAILY_MESSAGES_PER_IP` | Daily cap per hashed client IP, for example `20`. |
| `DAILY_MESSAGES_TOTAL` | Daily cap across the demo, for example `30`. |
| `MAX_MESSAGE_CHARS` | Maximum message length after trimming, defaults to `2000`. The composer also caps input at 2000. |
| `TRUST_PROXY` | Defaults to `false`, using the direct connection address. When `true`, uses the rightmost `X-Forwarded-For` address. |

Each daily limit is off when unset or empty; zero blocks live messages for that scope.
Counters persist in Postgres and reset at midnight UTC. Unknown conversations and invalid
content do not consume quota. An accepted turn still counts if it later fails.
Only enable `TRUST_PROXY` behind your own reverse proxy that appends the client address.
The application hashes IP addresses with SHA-256 before sending them to the database.

At Haiku 4.5 pricing of $1 per million input tokens and $5 per million output tokens,
a typical turn with 5,000 to 10,000 input tokens costs about one cent including a short
reply. A $10 monthly budget covers roughly 1,000 such turns; a total cap of 30 per day
leaves some headroom. These are estimates, not a dollar cap, since history and tool calls
can make turns cost more.

`GET /api/health` checks database connectivity without a visitor header, returning 200
with `{"status":"ok"}` or 503 on failure. A daily timer can call it to keep the free database active.

## Deploying the demo

The demo frontend runs on Vercel with `frontend` as the root directory and
`NEXT_PUBLIC_API_URL` set to the backend's address. The backend runs on one Ubuntu 24.04
server behind Caddy, which serves HTTPS on an sslip.io hostname. The `deploy` folder has:

- `configure.sh`, run from your machine, which prompts for each secret without echoing it,
  applies the migrations to the demo database and writes `/etc/loupe/backend.env` on the server.
- `setup.sh`, run on the server, which installs Docker and Caddy, opens the firewall, installs
  the backend and starts it with systemd. Running it again updates the server to the branch's latest commit.
- A daily timer that calls `GET /api/health` so the free database stays active.

```bash
FRONTEND_ORIGIN=https://your-app.vercel.app bash deploy/configure.sh ubuntu@203.0.113.7
scp deploy/setup.sh ubuntu@203.0.113.7:
ssh ubuntu@203.0.113.7 'sudo DOMAIN=203-0-113-7.sslip.io bash setup.sh'
```

Later updates can run `/opt/loupe/deploy/setup.sh` on the server instead. `FRONTEND_ORIGIN`
must match the Vercel URL, or the browser's CORS check rejects every request.

## Checks

The six gates are backend lint, type checking and tests, plus frontend lint, type checking
and tests. CI runs backend tests with `-rs` so a skipped test cannot be mistaken for a passing one.

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
