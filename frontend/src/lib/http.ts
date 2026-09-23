import { errorMessage } from './errorMessage'

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); this.name = 'ApiError' }
}

export async function requestResponse(path: string, init?: RequestInit, timeoutMs = 10000): Promise<Response> {
  const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
  const response = await fetch(`${base}${path}`, { ...init, signal: init?.signal ?? AbortSignal.timeout(timeoutMs) })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: { msg: string }) => item.msg).join('; ') : detail?.message ?? `Ошибка API: ${response.status}`
    throw new ApiError(errorMessage(detail?.code, message), response.status, detail?.code)
  }
  return response
}

export async function request<T>(path: string, init?: RequestInit, timeoutMs = 10000): Promise<T> {
  return (await requestResponse(path, init, timeoutMs)).json() as Promise<T>
}
