/* Typed-ish API client. Handles the per-run session token, JSON content type (required by the server on every
 * non-GET request) and Server-Sent Events. No secrets are ever handled here: credentials live on the server. */
const BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

let tokenPromise: Promise<string> | null = null;
function getToken(force = false): Promise<string> {
  if (force || !tokenPromise) {
    tokenPromise = fetch(`${BASE}/api/session`, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new ApiError(r.status, "Cannot reach the Studio API"); return r.json(); })
      .then((j) => j.token as string)
      .catch((e) => { tokenPromise = null; throw e; });
  }
  return tokenPromise;
}

async function request<T>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const token = await getToken();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method, cache: "no-store",
      headers: { "X-Session-Token": token, ...(method !== "GET" ? { "Content-Type": "application/json" } : {}) },
      body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the Studio API. Is `mcp-assistant-studio` running?");
  }
  if (res.status === 401 && retry) { await getToken(true); return request<T>(method, path, body, false); } // server restarted -> new token
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* not json */ }
  if (!res.ok) throw new ApiError(res.status, (data && data.error) || text.slice(0, 200) || res.statusText);
  return data as T;
}

export const api = {
  get: <T = any>(path: string) => request<T>("GET", path),
  post: <T = any>(path: string, body?: unknown) => request<T>("POST", path, body),
  del: <T = any>(path: string) => request<T>("DELETE", path),
};

/** Parse one SSE text buffer into events; returns parsed events and the unconsumed remainder. Pure -> unit-tested. */
export function parseSSE(buffer: string): { events: { event: string; data: any }[]; rest: string } {
  const events: { event: string; data: any }[] = [];
  const parts = buffer.split(/\r?\n\r?\n/);
  const rest = parts.pop() ?? "";
  for (const block of parts) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) continue;
    try { events.push({ event, data: JSON.parse(data.join("\n")) }); } catch { /* ignore malformed frame */ }
  }
  return { events, rest };
}

/** POST and consume an SSE stream. Aborting `signal` closes the connection (the server also gets /api/chat/stop). */
export async function streamPost(path: string, body: unknown, onEvent: (e: { event: string; data: any }) => void, signal?: AbortSignal) {
  const token = await getToken();
  const res = await fetch(`${BASE}${path}`, { method: "POST", signal, headers: { "X-Session-Token": token, "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try { msg = (await res.json()).error ?? msg; } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const { events, rest } = parseSSE(buf);
    buf = rest;
    events.forEach(onEvent);
  }
}
