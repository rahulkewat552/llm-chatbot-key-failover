"""LiteLLM gateway: key-pool failover + built-in response caching."""
import hashlib
import json
import logging
from dataclasses import dataclass

import litellm

from .config import settings

log = logging.getLogger("chat.llm")

ALLOWED_SIM_STATUSES = {429, 500, 502, 503}

# LiteLLM's cache returns the stored response, but some versions zero out `usage` on a hit.
# This side map keeps the usage of each live response so a hit reports the stored usage.
_usage_by_digest: dict[str, tuple[int, int]] = {}


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    resolution_source: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


def _new_cache():
    if settings.cache_type == "disk":
        return litellm.Cache(type="disk", disk_cache_dir=settings.cache_dir)
    return litellm.Cache(type="local")


def init_cache() -> None:
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    litellm.cache = _new_cache()
    # LiteLLM lazy-loads heavy modules on the first cache hit (~1s). Trigger that at startup with a
    # throwaway mocked call, then reset the cache, so the first real hit is as fast as every other.
    try:
        probe = dict(
            model=settings.model,
            messages=[{"role": "user", "content": "warm-up"}],
            api_key="warm-up",
            mock_response="warm-up",
            caching=True,
        )
        litellm.completion(**probe)
        litellm.completion(**probe)
    except Exception as exc:  # warm-up is best-effort
        log.warning("cache warm-up skipped (%s)", type(exc).__name__)
    litellm.cache = _new_cache()
    _usage_by_digest.clear()


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Invalid pairs are ignored."""
    sim: dict[str, int] = {}
    if not header:
        return sim
    for part in header.split(","):
        key, sep, status = part.partition("=")
        key = key.strip()
        try:
            code = int(status.strip())
        except ValueError:
            continue
        if sep and key and code in ALLOWED_SIM_STATUSES:
            sim[key] = code
    return sim


def _digest(messages: list[dict]) -> str:
    raw = json.dumps([settings.model, messages], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def generate(messages: list[dict], sim: dict[str, int] | None = None) -> LLMResult:
    sim = sim or {}
    digest = _digest(messages)
    # A simulated-failure request must exercise the key pool, so it bypasses the cache.
    use_cache = not sim
    attempts = 0

    for index, api_key in enumerate(settings.api_keys, start=1):
        key_id = f"key_{index}"
        simulated = sim.get(key_id, sim.get("*"))
        if simulated:
            log.warning("%s: simulated provider status %s", key_id, simulated)
            attempts += 1
            continue

        kwargs = dict(
            model=settings.model,
            messages=messages,
            api_key=api_key,
            temperature=0,
            timeout=settings.request_timeout,
            num_retries=0,
            caching=use_cache,
        )
        if settings.mock_response:
            kwargs["mock_response"] = settings.mock_response

        try:
            response = litellm.completion(**kwargs)
            reply = (response.choices[0].message.content or "").strip()
            if not reply:
                use_cache = False  # never serve or store an empty reply
                raise ValueError("empty reply from provider")
        except Exception as exc:  # 429, quota, 5xx, timeouts, auth, empty reply -> next key
                        detail = str(exc).replace(api_key, "***")[:300]
            print(f"[failover] {key_id} failed: {type(exc).__name__} status={getattr(exc, 'status_code', None)} {detail}", flush=True)
            attempts += 1
            continue

        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        hit = bool((getattr(response, "_hidden_params", None) or {}).get("cache_hit"))

        if hit:
            if not in_tok and digest in _usage_by_digest:
                in_tok, out_tok = _usage_by_digest[digest]
            return LLMResult(reply, "LLM_CACHE", settings.model, in_tok, out_tok, None, 0)

        _usage_by_digest[digest] = (in_tok, out_tok)
        return LLMResult(reply, "LIVE_INFERENCE", settings.model, in_tok, out_tok, key_id, attempts)

    raise AllProvidersUnavailable()
