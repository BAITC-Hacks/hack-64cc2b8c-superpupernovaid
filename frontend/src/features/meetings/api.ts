import { request } from '../../lib/http'

export type MediaAsset = {
  id: string
  meeting_id: string
  original_filename: string
  duration_seconds: number | null
  media_type: 'audio' | 'video'
  status: 'uploaded' | 'invalid'
}

export const meetingMediaApi = {
  upload(meetingId: string, file: File) {
    const body = new FormData()
    body.append('file', file)
    return request<MediaAsset>(`/meetings/${meetingId}/media`, { method: 'POST', body }, 900000)
  },
  preprocess(meetingId: string, mediaId: string) {
    return request(`/meetings/${meetingId}/media/${mediaId}/preprocess`, { method: 'POST' }, 960000)
  },
}

export type MeetingCreate = {
  title: string
  scheduled_at: string | null
  language_hint: 'ru' | 'kk' | 'mixed' | 'auto'
  expected_participant_count: number | null
  recording_consent_confirmed: boolean
}

export const meetingsApi = {
  create(payload: MeetingCreate) {
    return request<{ id: string }>('/meetings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },
}
