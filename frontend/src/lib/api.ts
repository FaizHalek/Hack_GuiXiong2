import { createSseParser } from './sse'
import { supabase } from './supabase'
import type { ChatEvent } from './types'

const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function errorFrom(res: Response): Promise<ApiError> {
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
      'Content-Type': 'application/json',
      ...(await authHeader()),
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

/** POST /chat and invoke `onEvent` for every server-sent event until the stream ends. */
export async function streamChat(
  body: { question: string; conversation_id?: string | null; label_ids: string[] },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeader()) },
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
