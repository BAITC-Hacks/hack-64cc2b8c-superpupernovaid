import { ApiError, request, requestResponse } from '../../lib/http'

export type ExportFormat = 'pdf' | 'docx'
export type ProtocolVersion = { id: string; meeting_id: string; created_at: string }
export type Reminder = { id: string; task_id: string; meeting_id: string; task: string; due_at: string; kind: 'due_soon' | 'overdue'; status: 'pending' | 'read' | 'cancelled'; created_at: string }
export type ProcessingRun = { id: string; media_id: string; status: 'queued' | 'running' | 'completed' | 'failed'; stage: string | null; steps: Record<string, string>; error_code: string | null; error_message: string | null }

export type Page<T> = { items: T[]; next_cursor: string | null }
export type Meeting = { id: string; title: string; scheduled_at: string | null; created_at: string; duration_seconds: number | null; expected_participant_count: number | null; processing_status: string }
export type Participant = { id: string; speaker_id: string; display_name: string | null; speech_share: number | null }
export type Task = { id: string; meeting_id: string; text: string; assignee: { id: string; display_name: string | null } | null; due_at: string | null; status: 'in_progress' | 'overdue' | 'completed'; priority: string }
export type ActionDetail = { id: string; assignee_name: string | null; deadline: string | null; deadline_text: string | null; needs_review: boolean }
export type AnalysisDetails = { topics: string[]; key_points: string[]; unresolved_questions: string[]; review_required: boolean; action_items: ActionDetail[]; review_issues: { reason: string }[] }
export type Result = { meeting: Meeting; participants: Participant[]; summary: string | null; decisions: { id: string; text: string }[]; tasks: Task[]; analysis_details?: AnalysisDetails | null }
export type Processing = { media_id: string | null; status: string; steps: { stage: string; status: string; progress: number | null; message: string }[] }
export type Segment = { id: string; started_at_ms: number; speaker_id: string; text: string }
export const labels: Record<string, string> = { queued: 'В очереди', canonicalizing: 'Уточнение текста', resolving_speakers: 'Определение участников', exporting: 'Подготовка протокола', draft: 'Черновик', uploaded: 'Загрузка', preprocessing: 'Подготовка аудио', transcribing: 'Распознавание', diarizing: 'Разделение спикеров', analyzing: 'Анализ', ready: 'Готов', failed: 'Ошибка', pending: 'Ожидает запуска', running: 'Выполняется', completed: 'Выполнено', unavailable: 'Недоступно', in_progress: 'В работе', overdue: 'Просрочено' }
export const dateLabel = (value: string | null) => value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }) : 'Не указан'
export const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export async function allPages<T>(path: string): Promise<T[]> {
  const items: T[] = []
  let cursor: string | null = null
  do {
    const page: Page<T> = await request(`${path}${path.includes('?') ? '&' : '?'}limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`)
    items.push(...page.items)
    cursor = page.next_cursor
  } while (cursor)
  return items
}
export const liveApi = {
  versions: (id: string, offset = 0) => request<ProtocolVersion[]>(`/meetings/${id}/protocol-versions?limit=50&offset=${offset}`),
  notifications: (status: string, offset = 0) => request<{ items: Reminder[] }>(`/notifications?limit=50&offset=${offset}${status ? `&status=${status}` : ''}`),
  scanReminders: () => request<{ created: number }>('/notifications/scan', { method: 'POST' }),
  readReminder: (id: string) => request<Reminder>(`/notifications/${id}/read`, { method: 'POST' }),
  process: (id: string, mediaId: string) => request<ProcessingRun>(`/meetings/${id}/process`, json('POST', { media_id: mediaId, export_formats: ['docx', 'pdf'] }), 30000),
  async processingRun(id: string) {
    try { return await request<ProcessingRun>(`/meetings/${id}/processing-run`) }
    catch (error) { if (error instanceof ApiError && error.status === 404 && error.code === 'processing_input_not_found') return null; throw error }
  },
  async exportFile(id: string, format: ExportFormat, versionId?: string) {
    const response = await requestResponse(`/meetings/${id}${versionId ? `/protocol-versions/${versionId}` : ''}/exports/${format}`, undefined, 180000)
    const type = response.headers.get('Content-Type')?.split(';')[0].trim()
    const expected = format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if (type !== expected) throw new Error('Сервер вернул неожиданный формат файла. Повторите экспорт.')
    return { blob: await response.blob(), filename: `meeting_${id}_${versionId ?? 'protocol'}.${format}` }
  },
  meetings: () => allPages<Meeting>('/meetings'),
  tasks: () => allPages<Task>('/tasks'),
  result: (id: string) => request<Result>(`/meetings/${id}/result`),
  processing: (id: string) => request<Processing>(`/meetings/${id}/processing`),
  transcript: (id: string, q: string, cursor: string | null) => request<Page<Segment>>(`/meetings/${id}/transcript?limit=100&q=${encodeURIComponent(q)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  task: (id: string, body: unknown) => request<Task>(`/tasks/${id}`, json('PATCH', body)),
  createTask: (id: string, body: unknown) => request<Task>(`/meetings/${id}/tasks`, json('POST', body)),
  rename: (id: string, speaker: string, display_name: string) => request<Participant>(`/meetings/${id}/participants/${encodeURIComponent(speaker)}`, json('PATCH', { display_name })),
  speech: (id: string, media: string) => request(`/meetings/${id}/media/${media}/speech`, { method: 'POST' }, 960000),
}
