# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + SQLite chatbot. LiteLLM provides the key-pool failover and the response cache.

## 1. Live URLs

- Frontend: `[<[add after deploy](https://llm-chat-failover-backend.onrender.com)>](https://llm-chat-failover-backend.onrender.com)`
- Backend: `[<add after deploy>](https://llm-chat-failover-backend.onrender.com/)` (try `/health`)
- Demo video: `<add link>`

## 2. Run locally: with Docker and without

### With Docker

```bash
cp .env.example .env     # put at least 2 real keys in LLM_API_KEYS
make up                  # frontend http://localhost:3000, backend http://localhost:8000
make down
```

SQLite lives in the named volume `app_data` mounted at `/data`, so history survives restarts.

### Without Docker

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000
python -m pytest            # backend tests (no real keys needed)

# frontend (new terminal)
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

### Deploy on Render

1. Push to GitHub, then create a Blueprint from `render.yaml` (backend as a Docker web service, frontend as a static site).
2. Backend env vars: `LLM_API_KEYS`, `ALLOWED_ORIGINS` (the frontend URL, no trailing slash), `ENABLE_FAILURE_SIMULATION=true`.
3. Frontend env var: `VITE_API_URL` (the backend URL). Redeploy the frontend after setting it, because Vite bakes it in at build time.
4. SQLite needs the persistent disk at `/data`, which requires a paid Render instance. A free instance loses history on restart.

## 3. Design decisions: key fallback, caching, SQLite session storage

**Key fallback.** `LLM_API_KEYS` is parsed into `key_1..key_N`. `llm.generate` tries each key in order with `litellm.completion(api_key=...)`. Any provider failure (429, quota, 5xx, timeout, auth error, empty reply) moves to the next key and increments `fallback_attempts`. If every key fails, the API returns `503 {"detail": "all providers unavailable"}` and nothing is written to history. Keys are never logged or returned; only `key_N` ids are.

**Caching.** LiteLLM's built-in cache (`litellm.Cache`, in-memory by default, `CACHE_TYPE=disk` for disk) is enabled on every call. The cache key is derived from the model and the full message list (system prompt + history + new message), so the same first message in a new session is a hit and a different message is never one. A hit is detected through `_hidden_params["cache_hit"]` and reported as `LLM_CACHE` with `key_id: null` and `fallback_attempts: 0`. Tokens on a hit are the usage stored with the cached response. `temperature=0` keeps live answers stable.

**Failure simulation.** With `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure` marks keys as failed for that request only. Those requests bypass the cache so the key pool is actually exercised.

**SQLite session storage.** The `messages` table follows the required schema, plus a `sessions` table that stores a per-session system prompt. The client sends only the new message; the backend rebuilds the context from SQLite. A user/assistant pair is written in one transaction only after a successful reply, so 422 and 503 responses leave no trace. The schema is created on startup and WAL mode is on.

## 4. Verification: how to see failover, cache hits and per-message token usage

```bash
API=http://localhost:8000
curl $API/health

# live, then cache hit from a brand-new session (same first message)
curl -s $API/chat -H 'content-type: application/json' -d '{"session_id":"a1","message":"What is the capital of France?"}'
curl -s $API/chat -H 'content-type: application/json' -d '{"session_id":"b2","message":"What is the capital of France?"}'   # LLM_CACHE, key_id null

# failover: key_1 fails, key_2 answers
curl -s $API/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"c3","message":"Tell me a joke"}'

# all keys fail: 503, nothing stored
curl -s -i $API/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"d4","message":"Hello"}'

# history
curl -s $API/sessions/a1/messages
```

In the UI, every reply shows source, model, latency, and input/output tokens for that request. Open "Session settings" and type `key_1=429` or `*=429` into "Simulate key failure" to demo failover.

## 5. Setup Used: your editor and AI tools

- Editor: `<your editor>`
- AI tools: Claude was used to draft and review the code; all behavior was checked against the assignment contract with the included tests.

## 6. Bonus features (if any)

- Per-session system prompt field (stored server-side and reused for the session).
- In-UI failure simulation field for demos.
- `key_id` and failed-key count shown next to each reply.
- Optional disk cache (`CACHE_TYPE=disk`) that survives restarts.
