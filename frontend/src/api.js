// Shared fetch wrapper.
//  - prefixes VITE_API_BASE
//  - attaches the JWT from AuthContext (registered via setTokenGetter)
//  - on 401, calls the handler AuthContext registers (logout + redirect to /login)
//  - throws an Error(with .status and .payload) on any non-2xx

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

let _getToken = () => null;
let _onUnauthorized = () => {};

export function setTokenGetter(fn) {
  _getToken = fn;
}
export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn;
}

async function request(path, { method = "GET", body, form, auth = true } = {}) {
  const headers = {};
  const token = _getToken();
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;

  let payload;
  if (form) {
    payload = form; // FormData - let the browser set the boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  } catch (e) {
    // fetch() throws TypeError on network failure / CORS block / server down
    const err = new Error(
      `Can't reach the API at ${API_BASE} — is the backend running? (${e.message})`
    );
    err.status = 0;
    err.cause = e;
    throw err;
  }

  if (res.status === 401) {
    _onUnauthorized();
    const err = new Error("Session expired - please sign in again.");
    err.status = 401;
    throw err;
  }

  const text = await res.text();
  const data = text ? safeJson(text) : null;

  if (!res.ok) {
    const err = new Error(errorMessage(data) || `Request failed (${res.status})`);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(data) {
  if (!data) return null;
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
      .join("; ");
  }
  return null;
}

export const api = {
  base: API_BASE,
  get: (p, opts) => request(p, { ...opts, method: "GET" }),
  post: (p, body, opts) => request(p, { ...opts, method: "POST", body }),
  put: (p, body, opts) => request(p, { ...opts, method: "PUT", body }),
  upload: (p, formData, opts) => request(p, { ...opts, method: "POST", form: formData }),
};
