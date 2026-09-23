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
    return request<MediaAsset>(`/meetings/${meetingId}/media`, { method: 'POST', body })
  },
  preprocess(meetingId: string, mediaId: string) {
    return request(`/meetings/${meetingId}/media/${mediaId}/preprocess`, { method: 'POST' })
  },
}
