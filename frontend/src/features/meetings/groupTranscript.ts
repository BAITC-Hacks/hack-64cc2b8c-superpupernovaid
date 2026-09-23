import type { Segment } from './liveApi'

// Group by speaker identity, never by the editable display name.
export function groupTranscript(segments: readonly Segment[]): Segment[] {
  const turns: Segment[] = []
  for (const segment of segments) {
    const previous = turns.at(-1)
    const text = segment.text.trim()
    if (previous && previous.speaker_id === segment.speaker_id) {
      const separator = !previous.text || !text || /^[,.;:!?…%)\]}»]/u.test(text) || /[(\[{«]$/u.test(previous.text) ? '' : ' '
      previous.text += separator + text
    } else {
      turns.push({ ...segment, text })
    }
  }
  return turns
}
