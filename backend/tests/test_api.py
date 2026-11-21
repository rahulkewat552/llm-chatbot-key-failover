from app import llm


def chat(client, sid, msg, headers=None, **extra):
    return client.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_live_then_cache_across_sessions(client, sid):
    a = chat(client, sid, "What is the capital of France?")
    assert a.status_code == 200
    ma = a.json()["metadata"]
    assert ma["resolution_source"] == "LIVE_INFERENCE"
    assert ma["key_id"] == "key_1" and ma["fallback_attempts"] == 0
    assert isinstance(ma["latency_ms"], int) and ma["input_tokens"] > 0 and ma["output_tokens"] > 0

    b = chat(client, sid + "-new", "What is the capital of France?")
    mb = b.json()["metadata"]
    assert mb["resolution_source"] == "LLM_CACHE"
    assert mb["key_id"] is None and mb["fallback_attempts"] == 0
    assert b.json()["reply"] == a.json()["reply"]
    assert mb["input_tokens"] == ma["input_tokens"] and mb["output_tokens"] == ma["output_tokens"]


def test_different_message_is_not_cached(client, sid):
    chat(client, sid, "What is the capital of France?")
    r = chat(client, sid + "-x", "What is the capital of Spain?")
    assert r.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_tokens_are_per_request_not_cumulative(client, sid):
    first = chat(client, sid, "hello there").json()["metadata"]
    second = chat(client, sid, "hello again friend").json()["metadata"]
    third = chat(client, sid + "-b", "hello there").json()["metadata"]
    # The mock provider reports fixed usage, so this checks that tokens are the
    # per-request usage object (never summed across the conversation).
    assert second["input_tokens"] == first["input_tokens"]
    assert third["input_tokens"] == first["input_tokens"]
    assert third["resolution_source"] == "LLM_CACHE"


def test_full_history_is_sent_to_the_model(client, sid, monkeypatch):
    sent = []
    real = llm.litellm.completion

    def spy(**kw):
        sent.append(kw["messages"])
        return real(**kw)

    monkeypatch.setattr(llm.litellm, "completion", spy)
    chat(client, sid, "My name is Rahul", system_prompt="Be brief.")
    chat(client, sid, "What is my name?")
    second = sent[-1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[0]["content"] == "Be brief."  # session system prompt persists
    assert second[1]["content"] == "My name is Rahul"
    assert second[-1]["content"] == "What is my name?"


def test_multi_turn_history_and_isolation(client, sid):
    chat(client, sid, "My name is Rahul")
    chat(client, sid, "What is my name?")
    r = client.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "My name is Rahul"
    assert {"resolution_source", "input_tokens", "output_tokens"} <= set(msgs[1]["metadata"])
    assert "metadata" not in msgs[0]
    assert all(m["role"] != "system" for m in msgs)

    other = chat(client, sid + "-other", "Hi").status_code
    assert other == 200
    assert len(client.get(f"/sessions/{sid}-other/messages").json()["messages"]) == 2


def test_unknown_session_404(client):
    r = client.get("/sessions/does-not-exist/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}


def test_validation_422(client, sid):
    assert client.post("/chat", json={"session_id": sid, "message": "   "}).status_code == 422
    assert client.post("/chat", json={"session_id": sid, "message": "x" * 4001}).status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "", "message": "hi"}).status_code == 422
    bad = client.post("/chat", content="{not json", headers={"content-type": "application/json"})
    assert bad.status_code == 422 and "detail" in bad.json()
    assert client.get(f"/sessions/{sid}/messages").status_code == 404  # nothing stored


def test_failover_on_simulated_429_and_500(client, sid):
    for header in ("key_1=429", "key_1=500", "key_1=502", "key_1=503"):
        r = chat(client, sid + header, f"failover test {header}", headers={"X-Simulate-Failure": header})
        assert r.status_code == 200, header
        m = r.json()["metadata"]
        assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
        assert m["resolution_source"] == "LIVE_INFERENCE"


def test_all_keys_fail_503_and_nothing_stored(client, sid):
    for header in ("*=429", "key_1=429,key_2=500"):
        r = chat(client, sid, "will fail", headers={"X-Simulate-Failure": header})
        assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_failover_bypasses_cache(client, sid):
    chat(client, sid, "cached question")
    r = chat(client, sid + "-b", "cached question", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.json()["metadata"]["key_id"] == "key_2"


def test_real_provider_failure_falls_over(client, sid, monkeypatch):
    calls = []
    real = llm.litellm.completion

    def flaky(**kw):
        calls.append(kw["api_key"])
        if kw["api_key"] == "test-key-a":
            raise RuntimeError("429 quota exceeded")
        return real(**kw)

    monkeypatch.setattr(llm.litellm, "completion", flaky)
    r = chat(client, sid, "real failure path")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert calls == ["test-key-a", "test-key-b"]


def test_custom_system_prompt_changes_cache_key(client, sid):
    a = chat(client, sid, "Say hi", system_prompt="You are a pirate.")
    b = chat(client, sid + "-b", "Say hi", system_prompt="You are a robot.")
    assert a.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert b.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_simulation_header_ignored_when_disabled(client, sid, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "enable_failure_simulation", False)
    r = chat(client, sid, "no sim", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200
