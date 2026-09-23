import { useState } from 'react'
import { useRemote, RemoteState } from '../../lib/useRemote'
import { liveApi, dateLabel, labels } from './liveApi'

const load = async () => { const [meetings, tasks] = await Promise.all([liveApi.meetings(), liveApi.tasks()]); return { meetings, tasks } }
export function LiveDashboard({ open, create }: { open: (id: string) => void; create: () => void }) {
  const state = useRemote(load, 15000)
  const [query, setQuery] = useState('')
  const { meetings = [], tasks = [] } = state.data ?? {}
  const visible = meetings.filter(m => m.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  return <>
    <section className="page-heading"><div><p className="eyebrow">ОБЗОР</p><h1>Совещания</h1><p>Записи и поручения вашей команды</p></div><button className="primary-button" onClick={create}>Новое совещание</button></section>
    <RemoteState {...state} retry={state.reload}/>
    {state.data && <>
      <section className="stat-grid">{[['Готовые совещания', meetings.filter(m => m.processing_status === 'ready').length], ['Активные поручения', tasks.filter(t => t.status !== 'completed').length], ['Просрочено', tasks.filter(t => t.status === 'overdue').length]].map(([title, count]) => <article className="stat-card" key={title}><div><small>{title}</small><strong>{count}</strong></div></article>)}</section>
      <section className="panel live-list-panel"><div className="panel-head"><h2>Все совещания <small>({visible.length})</small></h2><input aria-label="Поиск совещаний" placeholder="Найти совещание" value={query} onChange={e => setQuery(e.target.value)}/></div><div className="meeting-list">{visible.map(m => <button className="meeting-row" key={m.id} onClick={() => open(m.id)}><span className="meeting-main"><strong>{m.title}</strong><span>{dateLabel(m.scheduled_at ?? m.created_at)} · {m.duration_seconds === null ? 'Длительность неизвестна' : `${Math.ceil(m.duration_seconds / 60)} мин`}</span></span><span>{labels[m.processing_status] ?? m.processing_status}</span></button>)}</div>{!visible.length && <p className="empty-filter">{query ? 'Совещаний по вашему запросу не найдено.' : 'Совещаний пока нет. Загрузите первую запись.'}</p>}</section>
      <section className="panel live-section live-list-panel"><div className="panel-head"><h2>Требуют внимания</h2></div>{tasks.filter(t => t.status !== 'completed' && t.due_at).sort((a, b) => a.due_at!.localeCompare(b.due_at!)).slice(0, 5).map(t => <button className="meeting-row" key={t.id} onClick={() => open(t.meeting_id)}><span className="meeting-main"><strong>{t.text}</strong><span>{t.assignee?.display_name ?? 'Не назначен'} · {dateLabel(t.due_at)}</span></span><span>{labels[t.status]}</span></button>)}{!tasks.some(t => t.status !== 'completed' && t.due_at) && <p className="empty-filter">Нет активных поручений с указанным сроком.</p>}</section>
    </>}
  </>
}

