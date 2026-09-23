import { useEffect, useState } from 'react'
import { AppCard } from '../../components/ui/AppCard'
import { StatusBadge } from '../../components/ui/StatusBadge'
import { jobsApi } from './api'
import { useJob } from './useJob'

export function AgentWorkspace() {
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState('Проверка подключения…')
  const { job, error, busy, submit } = useJob()
  useEffect(() => {
    let cancelled = false
    jobsApi.health().then(info => { if (!cancelled) setMode(info.ai_mode === 'mock' ? 'Деморежим · без вызовов ИИ' : 'OpenAI Agents') })
      .catch(() => { if (!cancelled) setMode('API недоступен') })
    return () => { cancelled = true }
  }, [])
  return <>
    <header className="mb-5"><p className="eyebrow">AGENT WORKSPACE</p><h1 className="display-5 fw-semibold">От идеи к действию.</h1>
      <p className="text-secondary mt-3">Отправьте задачу агенту и отслеживайте результат обработки.</p>
      <span className="badge rounded-pill text-bg-light border">{mode}</span>
    </header>
    {error && <div className="alert alert-danger" role="alert">{error}</div>}
    <div className="row g-4">
      <div className="col-lg-6"><AppCard title="Новая задача"><form onSubmit={event => { event.preventDefault(); void submit(prompt) }}>
        <label htmlFor="prompt" className="form-label">Что нужно сделать?</label>
        <textarea id="prompt" value={prompt} onChange={event => setPrompt(event.target.value)} className="form-control" rows={7} maxLength={10000} required disabled={busy} placeholder="Например: составь план разработки прототипа…" />
        <div className="d-flex justify-content-between align-items-center mt-3"><small className="text-secondary">{prompt.length} / 10 000</small>
          <button className="btn btn-primary px-4" disabled={busy || !prompt.trim()}>{busy && <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />}{busy ? 'Обрабатывается…' : 'Запустить'}</button>
        </div>
      </form></AppCard></div>
      <div className="col-lg-6"><AppCard title="Результат"><div aria-live="polite">
        {!job ? <div className="empty-state text-secondary">Результат появится здесь после отправки задачи.</div> : <>
          <StatusBadge status={job.status} /><p className="small text-secondary mt-3 text-break">ID: {job.id}</p>
          {job.result ? <p className="result-text">{job.result}</p> : job.error ? <p className="text-danger">{job.error}</p> : <p className="text-secondary">Ожидаем результат. Если задача долго остаётся в очереди, проверьте запуск воркера.</p>}
        </>}
      </div></AppCard></div>
    </div>
  </>
}
