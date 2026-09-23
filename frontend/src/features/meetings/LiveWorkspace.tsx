import { useCallback, useMemo, useState } from 'react'
import { RemoteState, useRemote } from '../../lib/useRemote'
import { CreateTask, TaskList } from '../tasks/LiveTasks'
import { ProtocolExport } from './ProtocolExport'
import { errorMessage } from '../../lib/errorMessage'
import { ProtocolHistory } from './ProtocolHistory'
import { AnalysisNotes } from './AnalysisNotes'
import { meetingMediaApi } from './api'
import { groupTranscript } from './groupTranscript'
import { liveApi, allPages, dateLabel, labels, type Participant, type Segment, type ProcessingRun } from './liveApi'

function Speaker({ meetingId, participant, refresh }: { meetingId: string; participant: Participant; refresh: () => void }) {
  const [name, setName] = useState(participant.display_name ?? participant.speaker_id)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <form className="live-speaker" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await liveApi.rename(meetingId, participant.speaker_id, name.trim()); refresh() }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось сохранить имя') }
    finally { setBusy(false) }
  }}><label>{participant.speaker_id}<input aria-label={`Имя ${participant.speaker_id}`} maxLength={255} value={name} onChange={e => setName(e.target.value)}/></label><span>{participant.speech_share === null ? 'Доля речи неизвестна' : `${Math.round(participant.speech_share * 100)}% речи`}</span><button className="text-button" disabled={busy || !name.trim()}>Сохранить</button>{error && <p role="alert">{error}</p>}</form>
}

function Transcript({ meetingId, participants }: { meetingId: string; participants: Participant[] }) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const load = useCallback(() => allPages<Segment>(`/meetings/${meetingId}/transcript`), [meetingId])
  const state = useRemote(load)
  const turns = useMemo(() => groupTranscript(state.data ?? []), [state.data])
  const visible = useMemo(() => {
    const needle = search.toLocaleLowerCase('ru-RU')
    return turns.filter(turn => turn.text.toLocaleLowerCase('ru-RU').includes(needle))
  }, [turns, search])
  return <section className="panel transcript-card">
    <form className="transcript-tools" onSubmit={e => { e.preventDefault(); setSearch(query.trim()) }}>
      <div><h2>Транскрипт</h2><p>Реплики сгруппированы по спикерам. Поиск показывает всю реплику.</p></div>
      <label><input aria-label="Поиск по транскрипту" maxLength={200} value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск по тексту"/></label>
      <button className="secondary-button">Найти</button>
      <button type="button" className="text-button" disabled={state.loading} onClick={state.reload}>Обновить</button>
    </form>
    <RemoteState {...state} retry={state.reload}/>
    <div className="transcript-list">{visible.map(s => <article className="transcript-row" key={s.id}>
      <span className="timecode">{[Math.floor(s.started_at_ms / 3600000), Math.floor(s.started_at_ms / 60000) % 60, Math.floor(s.started_at_ms / 1000) % 60].map(v => String(v).padStart(2, '0')).join(':')}</span>
      <div><strong>{participants.find(p => p.speaker_id === s.speaker_id)?.display_name ?? s.speaker_id}</strong><p>{s.text}</p></div>
    </article>)}</div>
    {!state.loading && !state.error && !visible.length && <p className="empty-filter">{search ? 'Реплик по вашему запросу не найдено.' : 'Транскрипт появится после распознавания.'}</p>}
  </section>
}

const continuePolling = ({ run, processing }: { run: ProcessingRun | null; processing: { media_id: string | null } }) => !run || run.media_id !== processing.media_id || run.status === 'queued' || run.status === 'running'

export function LiveWorkspace({ meetingId, back }: { meetingId: string; back: () => void }) {
  const load = useCallback(async () => { const [result, processing, run] = await Promise.all([liveApi.result(meetingId), liveApi.processing(meetingId), liveApi.processingRun(meetingId)]); return { result, processing, run } }, [meetingId])
  const state = useRemote(load, 2000, continuePolling)
  const [tab, setTab] = useState('summary')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const process = async () => {
    if (!state.data?.processing.media_id) return
    setBusy(true); setError('')
    try {
      await liveApi.process(meetingId, state.data.processing.media_id)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Обработка не завершена') }
    finally { setBusy(false); state.reload() }
  }
  const transcribeOnly = async () => {
    const mediaId = state.data?.processing.media_id
    if (!mediaId) return
    setBusy(true); setError('')
    try {
      await meetingMediaApi.preprocess(meetingId, mediaId)
      await liveApi.speech(meetingId, mediaId)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось распознать запись') }
    finally { setBusy(false); state.reload() }
  }
  const result = state.data?.result
  const processing = state.data?.processing
  const run = state.data?.run?.media_id === processing?.media_id ? state.data?.run : null
  const running = busy || run?.status === 'queued' || run?.status === 'running' || processing?.steps.some(s => s.status === 'running')
  const analyzed = processing?.steps.some(s => s.stage === 'analyzing' && s.status === 'completed') ?? false
  return <><button className="text-button" onClick={back}>← Все совещания</button><RemoteState {...state} retry={state.reload}/>{result && processing && <>
    <section className="page-heading"><div><p className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</p><h1>{result.meeting.title}</h1><p>{dateLabel(result.meeting.scheduled_at ?? result.meeting.created_at)} · {result.participants.length} участников</p></div><ProtocolExport meetingId={meetingId} available={analyzed && !running}/></section>
    <section className="panel live-form"><h2>{labels[processing.status] ?? processing.status}</h2><div className="pipeline">{processing.steps.map(s => <span key={s.stage} className={s.status === 'completed' ? 'done' : ''}>{labels[s.stage] ?? s.stage}: {labels[s.status] ?? s.status}{s.progress !== null ? ` (${s.progress}%)` : ''}</span>)}</div>{processing.media_id && run?.status !== 'completed' && <button className="primary-button" disabled={running} onClick={() => void process()}>{running ? (run?.status === 'queued' ? 'В очереди…' : 'Обработка…') : run?.status === 'failed' ? 'Повторить обработку' : 'Обработать и создать протокол'}</button>}{processing.media_id && !analyzed && <button className="secondary-button" disabled={running} onClick={() => void transcribeOnly()}>Только транскрипт (без ИИ-анализа)</button>}{error && <p role="alert" className="form-error">{error}</p>}{!processing.media_id && <p>К совещанию пока не прикреплена запись.</p>}<p>Распознавание — NVIDIA Cloud; анализ текста — настроенный на сервере ИИ. Обработка продолжается в фоне.</p>{run?.error_message && <p role="alert" className="form-error">{errorMessage(run.error_code, run.error_message)}</p>}</section>
    <div className="workspace-tabs">{[['summary', 'Саммари'], ['transcript', 'Транскрипт'], ['tasks', 'Поручения'], ['history', 'История протоколов']].map(([id, title]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{title}</button>)}</div>
    {tab === 'summary' && <div className="summary-layout"><div className="summary-main"><section className="panel summary-card"><h2>Краткое содержание</h2><p style={{ whiteSpace: 'pre-wrap' }}>{result.summary ?? 'Саммари ещё не сформировано.'}</p></section><section className="panel decision-card"><h2>Решения</h2>{result.decisions.length ? <ul>{result.decisions.map(d => <li key={d.id}>{d.text}</li>)}</ul> : <p>Решений пока нет.</p>}</section></div><aside className="panel live-form"><h2>Участники</h2>{result.participants.map(p => <Speaker key={`${p.id}:${p.display_name}`} meetingId={meetingId} participant={p} refresh={state.reload}/>)}{!result.participants.length && <p>Участники появятся после распознавания.</p>}</aside></div>}
    {tab === 'transcript' && <Transcript key={processing.status} meetingId={meetingId} participants={result.participants}/>}
    {tab === 'summary' && <AnalysisNotes details={result.analysis_details}/>}
    {tab === 'tasks' && <><p>Для напоминаний задайте точные дату и время. Формулировки из записи показаны отдельно и требуют проверки.</p><TaskList tasks={result.tasks} actionDetails={result.analysis_details?.action_items} participants={result.participants} refresh={state.reload}/><CreateTask meetingId={meetingId} participants={result.participants} refresh={state.reload}/></>}
    {tab === 'history' && <ProtocolHistory meetingId={meetingId}/>}
  </>}</>
}
