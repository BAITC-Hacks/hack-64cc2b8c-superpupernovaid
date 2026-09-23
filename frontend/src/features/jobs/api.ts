import { request } from '../../lib/http'
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export interface Job { id: string; prompt: string; status: JobStatus; result: string | null; error: string | null; created_at: string }
export const jobsApi = {
  create: (prompt: string) => request<Job>('/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }) }),
  get: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
  health: () => request<{ status: string; ai_mode: 'mock' | 'openai' }>('/health'),
}
