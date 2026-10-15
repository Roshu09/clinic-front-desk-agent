// Thin fetch wrapper. Same-origin in production (FastAPI serves the build); proxied in `npm run dev`.
const BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options) {
  const response = await fetch(`${BASE}${path}`, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || body.error || {};
    throw new Error(detail.message || `Request failed (${response.status})`);
  }
  return body;
}

export const api = {
  summary: () => request("/api/summary"),
  handoffs: () => request("/api/handoffs"),
  conversations: () => request("/api/conversations"),
  conversation: (id) => request(`/api/conversations/${encodeURIComponent(id)}`),
  resolve: (id) => request(`/api/handoffs/${encodeURIComponent(id)}/resolve`, { method: "POST" }),
  rerun: (id) => request(`/api/conversations/${encodeURIComponent(id)}/rerun?times=3`, { method: "POST" }),
  seed: () => request("/api/demo/seed", { method: "POST" }),
};
