import { createSseParser } from './sse'
import { getToken, setToken } from './session'
import type { ChatEvent } from './types'

const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function authHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function errorFrom(res: Response): Promise<ApiError> {
  // An expired or revoked token signs the user out instead of leaving every page in an error state.
  if (res.status === 401 && getToken()) setToken(null)
  let message = res.statusText
  try {
    const body = await res.json()
    message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message)
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...authHeader(),
      ...(init.headers as Record<string, string> | undefined),
    },
  })
  if (!res.ok) throw await errorFrom(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
/** POST multipart form data (file uploads); the browser sets the boundary header. */
export const postForm = <T>(path: string, form: FormData) => api<T>(path, { method: 'POST', body: form })

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw await errorFrom(res)
  const { access_token } = (await res.json()) as { access_token: string }
  setToken(access_token)
}

/** POST /chat and invoke `onEvent` for every server-sent event until the stream ends. */
export async function streamChat(
  body: { question: string; conversation_id?: string | null; label_ids: string[] },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) throw await errorFrom(res)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parse = createSseParser<ChatEvent>()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    parse(decoder.decode(value, { stream: true })).forEach(onEvent)
  }
}
