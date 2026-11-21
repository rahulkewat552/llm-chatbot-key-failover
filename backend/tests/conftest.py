import os
import tempfile
import uuid

import pytest

_tmp = tempfile.mkdtemp()
os.environ.update(
    LLM_API_KEYS="test-key-a,test-key-b",
    DATABASE_URL=f"sqlite:///{_tmp}/app.db",
    ALLOWED_ORIGINS="http://localhost:3000",
    ENABLE_FAILURE_SIMULATION="true",
    LLM_MOCK_RESPONSE="The capital of France is Paris.",
    CACHE_TYPE="local",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:  # lifespan resets the cache
        yield c


@pytest.fixture
def sid():
    return f"s-{uuid.uuid4().hex[:8]}"
