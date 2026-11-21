import os
from dataclasses import dataclass


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@dataclass
class Settings:
    api_keys: list[str]
    database_url: str
    allowed_origins: list[str]
    enable_failure_simulation: bool
    model: str
    default_system_prompt: str
    cache_type: str
    cache_dir: str
    request_timeout: int
    debug_errors: bool
    mock_response: str | None  # test-only: LiteLLM returns this instead of calling the provider

    @property
    def db_path(self) -> str:
        url = self.database_url
        for prefix in ("sqlite:///",):
            if url.startswith(prefix):
                return url[len(prefix):]
        return url

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_keys=_list(os.getenv("LLM_API_KEYS")),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
            allowed_origins=[o.rstrip("/") for o in _list(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000"))],
            enable_failure_simulation=_bool(os.getenv("ENABLE_FAILURE_SIMULATION")),
            model=os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash"),
            default_system_prompt=os.getenv(
                "DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."
            ),
            cache_type=os.getenv("CACHE_TYPE", "local").lower(),
            cache_dir=os.getenv("CACHE_DIR", "/data/llm_cache"),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
            debug_errors=_bool(os.getenv("DEBUG_ERRORS")),
            mock_response=os.getenv("LLM_MOCK_RESPONSE") or None,
        )


settings = Settings.from_env()
