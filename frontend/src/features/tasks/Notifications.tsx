import { useCallback, useState } from 'react'
import { RemoteState, useRemote } from '../../lib/useRemote'
import { dateLabel, liveApi } from '../meetings/liveApi'

export function Notifications({ open }: { open: (id: string) => void }) {
  const [status, setStatus] = useState('pending')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const load = useCallback(() => liveApi.notifications(status, offset), [status, offset])
  const state = useRemote(load, 30000)
  const act = async (id?: string) => {
    setBusy(true); setError(''); setNotice('')
    try {
      if (id) await liveApi.readReminder(id)
      else { const result = await liveApi.scanReminders(); setNotice(`Новых напоминаний: ${result.created}`) }
      state.reload()
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось обновить напоминания') }
    finally { setBusy(false) }
  }
  return <><section className="page-heading"><div><p className="eyebrow">КОНТРОЛЬ СРОКОВ</p><h1>Уведомления</h1><p>Напоминания о просроченных поручениях и сроках в ближайшие 24 часа.</p></div><button className="primary-button" disabled={busy} onClick={() => void act()}>{busy ? 'Обновляем…' : 'Проверить сроки'}</button></section>
    <section className="panel live-form"><div className="filter-tabs">{[['pending', 'Непрочитанные'], ['read', 'Прочитанные'], ['', 'Все']].map(([id, label]) => <button className={status === id ? 'active' : ''} key={id} onClick={() => { setStatus(id); setOffset(0) }}>{label}</button>)}</div>
      <RemoteState {...state} retry={state.reload}/>{error && <p role="alert" className="form-error">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!state.loading && state.data?.items.map(n => <article className="history-row" key={n.id}><div><strong>{n.task}</strong><p>{n.kind === 'overdue' ? 'Срок истёк' : 'Скоро срок'} · {dateLabel(n.due_at)}{n.status === 'cancelled' ? ' · Неактуально' : n.status === 'read' ? ' · Прочитано' : ''}</p><button className="text-button" onClick={() => open(n.meeting_id)}>Открыть совещание</button></div>{n.status === 'pending' && <button className="secondary-button" disabled={busy} onClick={() => void act(n.id)}>Прочитано</button>}</article>)}
      {!state.loading && !state.error && !state.data?.items.length && <p className="empty-filter">Напоминаний нет.</p>}
      <div className="meeting-actions"><button className="secondary-button" disabled={!offset || state.loading} onClick={() => setOffset(offset - 50)}>Назад</button><button className="secondary-button" disabled={state.data?.items.length !== 50 || state.loading} onClick={() => setOffset(offset + 50)}>Далее</button></div>
    </section></>
}
