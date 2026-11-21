export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

function describeError(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Try again in a moment.";
  if (status === 422) {
    const first = Array.isArray(body?.detail) ? body.detail[0] : null;
    const field = first?.loc?.[first.loc.length - 1];
    const msg = first?.msg?.replace(/^Value error, /, "");
    return field ? `Check the ${field} field: ${msg}` : "The message was rejected. Check its length and try again.";
  }
  return typeof body?.detail === "string" ? body.detail : `Request failed (HTTP ${status}).`;
}

export async function sendChat({ sessionId, message, systemPrompt, simulateFailure }) {
  const headers = { "Content-Type": "application/json" };
  if (simulateFailure) headers["X-Simulate-Failure"] = simulateFailure;
  const payload = { session_id: sessionId, message };
  if (systemPrompt) payload.system_prompt = systemPrompt;

  let res;
  try {
    res = await fetch(`${API_URL}/chat`, { method: "POST", headers, body: JSON.stringify(payload) });
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  if (!res.ok) throw new Error(describeError(res.status, body));
  return body;
}
