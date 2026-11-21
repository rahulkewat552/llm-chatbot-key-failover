import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError  # noqa: F401  (default 422 handler is kept)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, llm
from .config import settings
from .schemas import ChatRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chat")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    llm.init_cache()
    if len(settings.api_keys) < 2:
        log.warning("Only %d API key(s) configured; failover needs at least 2", len(settings.api_keys))
    yield


app = FastAPI(title="LLM Chatbot with Key Failover and Response Caching", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health():
    try:
        db.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="database unreachable")
    if not settings.api_keys:
        raise HTTPException(status_code=503, detail="key pool not loaded")
    return {
        "status": "ok",
        "keys_configured": len(settings.api_keys),
        "cache_enabled": llm.litellm.cache is not None,
    }


@app.post("/chat")
def chat(body: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    started = time.perf_counter()
    sim = llm.parse_simulation(x_simulate_failure) if settings.enable_failure_simulation else {}

    history, stored_prompt = db.load_session(body.session_id)
    system_prompt = body.system_prompt or stored_prompt or settings.default_system_prompt
    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": body.message},
    ]

    try:
        result = llm.generate(messages, sim)
    except llm.AllProvidersUnavailable as exc:
        body_503 = {"detail": "all providers unavailable"}
        if settings.debug_errors:  # temporary diagnostics, off by default
            body_503["errors"] = exc.errors
        return JSONResponse(status_code=503, content=body_503)

    metadata = {
        "resolution_source": result.resolution_source,
        "model": result.model,
        "latency_ms": max(0, int(round((time.perf_counter() - started) * 1000))),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "key_id": result.key_id,
        "fallback_attempts": result.fallback_attempts,
    }
    db.save_exchange(body.session_id, body.message, result.reply, metadata, body.system_prompt or None)
    return {"session_id": body.session_id, "reply": result.reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    messages = db.get_messages(session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": messages}
