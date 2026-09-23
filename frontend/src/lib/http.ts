export async function request<T>(path: string, init?: RequestInit, timeoutMs = 10000): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { ...init, signal: AbortSignal.timeout(timeoutMs) })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : payload?.detail?.message ?? `Ошибка API: ${response.status}`)
  }
  return response.json() as Promise<T>
}
