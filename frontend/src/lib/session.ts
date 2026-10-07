/** The login token, kept in localStorage so a refresh keeps the user signed in. */

const KEY = 'auth_token'
type Listener = (token: string | null) => void
const listeners = new Set<Listener>()

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: the session lasts until the page closes */
  }
  listeners.forEach((fn) => fn(token))
}

export function onTokenChange(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
