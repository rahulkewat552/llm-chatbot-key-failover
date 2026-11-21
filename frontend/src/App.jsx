import { useEffect, useRef, useState } from "react";
import { sendChat } from "./api.js";

const newSessionId = () =>
  "s-" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(16).slice(2, 10));

function Meta({ m }) {
  const cached = m.resolution_source === "LLM_CACHE";
  return (
    <dl className="meta">
      <div>
        <dt>source</dt>
        <dd>
          <span data-testid="meta-source" className={cached ? "pill cache" : "pill live"}>
            {m.resolution_source}
          </span>
        </dd>
      </div>
      <div>
        <dt>model</dt>
        <dd data-testid="meta-model">{m.model}</dd>
      </div>
      <div>
        <dt>latency</dt>
        <dd data-testid="meta-latency">{m.latency_ms} ms</dd>
      </div>
      <div>
        <dt>tokens in</dt>
        <dd data-testid="meta-input-tokens">{m.input_tokens}</dd>
      </div>
      <div>
        <dt>tokens out</dt>
        <dd data-testid="meta-output-tokens">{m.output_tokens}</dd>
      </div>
      <div>
        <dt>answered by</dt>
        <dd>{m.key_id ?? "cache"}</dd>
      </div>
      {m.fallback_attempts > 0 && (
        <div>
          <dt>failed keys</dt>
          <dd>{m.fallback_attempts}</dd>
        </div>
      )}
    </dl>
  );
}

export default function App() {
  const [sessionId] = useState(newSessionId); // new session on every page load
  const [items, setItems] = useState([]);
  const [text, setText] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, busy]);

  async function send() {
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setBusy(true);
    setItems((prev) => [...prev, { kind: "user", text: message }]);
    try {
      const data = await sendChat({
        sessionId,
        message,
        systemPrompt: systemPrompt.trim(),
        simulateFailure: simulate.trim(),
      });
      setItems((prev) => [...prev, { kind: "assistant", text: data.reply, meta: data.metadata }]);
    } catch (err) {
      setItems((prev) => [...prev, { kind: "error", text: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="shell">
      <header className="top">
        <h1>Failover chat</h1>
        <span className="session">session {sessionId}</span>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>
          System prompt
          <textarea
            data-testid="system-prompt-input"
            rows={2}
            placeholder="You are a helpful, concise assistant."
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </label>
        <label>
          Simulate key failure
          <input
            value={simulate}
            placeholder="key_1=429"
            onChange={(e) => setSimulate(e.target.value)}
          />
          <small>Applies to each message you send. Example: key_1=429 or *=429</small>
        </label>
      </details>

      <main className="log" aria-live="polite">
        {items.length === 0 && (
          <p className="empty">Ask anything. Send the same question in a new tab to see a cache hit.</p>
        )}
        {items.map((it, i) =>
          it.kind === "user" ? (
            <div key={i} className="msg user" data-testid="user-message">
              {it.text}
            </div>
          ) : it.kind === "assistant" ? (
            <div key={i} className="msg assistant" data-testid="assistant-message">
              <p className="reply">{it.text}</p>
              <Meta m={it.meta} />
            </div>
          ) : (
            <div key={i} className="msg error" role="alert" data-testid="error-message">
              {it.text}
            </div>
          )
        )}
        {busy && <div className="msg pending">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer className="composer">
        <textarea
          data-testid="chat-input"
          rows={1}
          placeholder="Type a message"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={4000}
        />
        <button data-testid="send-button" onClick={send} disabled={busy || !text.trim()}>
          Send
        </button>
      </footer>
    </div>
  );
}
