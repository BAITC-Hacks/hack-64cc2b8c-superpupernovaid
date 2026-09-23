import { useState } from 'react'
import { useRemote, RemoteState } from '../../lib/useRemote'
import { liveApi, dateLabel, labels, type Task, type Participant, type ActionDetail } from '../meetings/liveApi'

function SourceDetails({ detail }: { detail?: ActionDetail }) {
  if (!detail) return null
  return <div className="task-source"><small>Из записи: {detail.assignee_name ? `исполнитель — ${detail.assignee_name}` : 'исполнитель не определён'}; {detail.deadline_text ? `срок — «${detail.deadline_text}»` : 'срок не указан'}.{detail.needs_review ? ' Требует проверки.' : ''}</small></div>
}

function TaskEditor({ task, participants, done }: { task: Task; participants: Participant[]; done: (saved: boolean) => void }) {
  const [text, setText] = useState(task.text)
  const [assignee, setAssignee] = useState(task.assignee?.id ?? '')
  const [due, setDue] = useState(() => {
    if (!task.due_at) return ''
    const date = new Date(task.due_at)
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <form className="live-form task-editor" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      await liveApi.task(task.id, { text: text.trim(), assignee_id: assignee || null, due_at: due ? new Date(due).toISOString() : null })
      done(true)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось сохранить поручение') }
    finally { setBusy(false) }
  }}><label>Поручение<textarea required maxLength={10000} value={text} onChange={e => setText(e.target.value)}/></label>
    <label>Ответственный<select value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">Не назначен</option>{participants.map(p => <option key={p.id} value={p.id}>{p.display_name ?? p.speaker_id}</option>)}</select></label>
    <label>Срок (ваше местное время)<input type="datetime-local" value={due} onChange={e => setDue(e.target.value)}/></label>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="meeting-actions"><button className="primary-button" disabled={busy || !text.trim()}>{busy ? 'Сохраняем…' : 'Сохранить'}</button><button className="secondary-button" type="button" disabled={busy} onClick={() => done(false)}>Отмена</button></div>
  </form>
}

export function TaskList({ tasks, refresh, open, participants, actionDetails }: { tasks: Task[]; refresh: () => void; open?: (id: string) => void; participants?: Participant[]; actionDetails?: ActionDetail[] }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const toggle = async (task: Task) => {
    setBusy(task.id); setError('')
    try { await liveApi.task(task.id, { status: task.status === 'completed' ? 'in_progress' : 'completed' }); refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить статус') }
    finally { setBusy(null) }
  }
  const visible = tasks.filter(t => (!status || t.status === status) && `${t.text} ${t.assignee?.display_name ?? ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  return <section className="panel tasks-panel">
    <div className="task-toolbar"><div className="filter-tabs">{['', 'in_progress', 'overdue', 'completed'].map(s => <button key={s} className={status === s ? 'active' : ''} onClick={() => setStatus(s)}>{labels[s] ?? 'Все'} ({tasks.filter(t => !s || t.status === s).length})</button>)}</div><input aria-label="Поиск поручений" placeholder="Найти поручение" value={query} onChange={e => setQuery(e.target.value)}/></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {visible.map(t => <div className="live-task" key={t.id}><input type="checkbox" aria-label={`Выполнено: ${t.text}`} checked={t.status === 'completed'} disabled={busy !== null || editing !== null} onChange={() => void toggle(t)}/><div><strong>{t.text}</strong><p>{t.assignee?.display_name ?? (t.assignee ? 'Участник без имени' : 'Не назначен')} · {dateLabel(t.due_at)} · {labels[t.status]}</p><SourceDetails detail={actionDetails?.find(d => d.id === t.id)}/>{open && <button className="text-button" onClick={() => open(t.meeting_id)}>Открыть совещание</button>}{participants && <button className="text-button" disabled={editing !== null || busy !== null} onClick={() => setEditing(t.id)}>Изменить</button>}{editing === t.id && participants && <TaskEditor task={t} participants={participants} done={saved => { setEditing(null); if (saved) refresh() }}/>}</div></div>)}
    {!visible.length && <p className="empty-filter">Поручений не найдено.</p>}
  </section>
}

export function CreateTask({ meetingId, participants, refresh }: { meetingId: string; participants: Participant[]; refresh: () => void }) {
  const [text, setText] = useState('')
  const [assignee, setAssignee] = useState('')
  const [due, setDue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <form className="panel live-form" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await liveApi.createTask(meetingId, { text: text.trim(), assignee_id: assignee || null, due_at: due ? new Date(due).toISOString() : null }); setText(''); setDue(''); setAssignee(''); refresh() }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось создать поручение') }
    finally { setBusy(false) }
  }}><h2>Добавить поручение</h2><label>Текст<input required maxLength={10000} value={text} onChange={e => setText(e.target.value)}/></label><label>Ответственный<select value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">Не назначен</option>{participants.map(p => <option key={p.id} value={p.id}>{p.display_name ?? p.speaker_id}</option>)}</select></label><label>Срок<input type="datetime-local" value={due} onChange={e => setDue(e.target.value)}/></label>{error && <p role="alert">{error}</p>}<button className="primary-button" disabled={busy || !text.trim()}>{busy ? 'Сохраняем…' : 'Добавить'}</button></form>
}

export function LiveTasks({ open }: { open: (id: string) => void }) {
  const state = useRemote(liveApi.tasks, 15000)
  return <><section className="page-heading"><div><p className="eyebrow">КОНТРОЛЬ ИСПОЛНЕНИЯ</p><h1>Поручения</h1><p>Добавить поручение можно в рабочем пространстве совещания.</p></div></section><RemoteState {...state} retry={state.reload}/>{state.data && <TaskList tasks={state.data} refresh={state.reload} open={open}/>}</>
}
