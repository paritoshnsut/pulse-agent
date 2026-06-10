// Thin fetch wrapper. The token comes from whichever auth mode is active
// (Supabase session, family password token, or "dev") via a provider that
// App.jsx installs at boot.

let tokenProvider = () => null;
let onUnauthorized = () => {};

export function setTokenProvider(fn) { tokenProvider = fn; }
export function setOnUnauthorized(fn) { onUnauthorized = fn; }

export async function api(path, opts = {}) {
  const token = await tokenProvider();
  const res = await fetch(path, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { onUnauthorized(); throw new Error('Signed out'); }
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    throw new Error(detail || res.statusText);
  }
  return res.json();
}
