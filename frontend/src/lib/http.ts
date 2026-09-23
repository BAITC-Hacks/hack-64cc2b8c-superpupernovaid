export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { ...init, signal: AbortSignal.timeout(10000) })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `Ошибка API: ${response.status}`)
  }
  return response.json() as Promise<T>
}
