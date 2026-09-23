import { useEffect, useRef, useState } from 'react'
import { jobsApi, type Job } from './api'

export function useJob() {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const submitting = useRef(false)
  const busy = sending || job?.status === 'queued' || job?.status === 'running'

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const id = job.id
    async function poll() {
      let delay = 1500
      try {
        const updated = await jobsApi.get(id)
        if (cancelled) return
        setJob(updated)
        setError('')
        if (!['queued', 'running'].includes(updated.status)) return
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Ошибка соединения')
        delay = 5000
      }
      if (!cancelled) timer = setTimeout(poll, delay)
    }
    timer = setTimeout(poll, 500)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [job?.id, job?.status])

  async function submit(prompt: string) {
    if (busy || submitting.current) return
    submitting.current = true
    setSending(true)
    setError('')
    try { setJob(await jobsApi.create(prompt)) }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось отправить запрос') }
    finally { submitting.current = false; setSending(false) }
  }
  return { job, error, busy, submit }
}
