import { useCallback, useState } from 'react'
import { RemoteState, useRemote } from '../../lib/useRemote'
import { dateLabel, liveApi } from './liveApi'
import { ProtocolExport } from './ProtocolExport'

export function ProtocolHistory({ meetingId }: { meetingId: string }) {
  const [offset, setOffset] = useState(0)
  const load = useCallback(() => liveApi.versions(meetingId, offset), [meetingId, offset])
  const state = useRemote(load)
  return <section className="panel live-form"><div className="panel-head"><h2>История протоколов</h2><button className="text-button" onClick={state.reload}>Обновить</button></div>
    <p>Сохранённые версии доступны независимо от текущей обработки. Новая версия появляется при экспорте изменённого протокола.</p>
    <RemoteState {...state} retry={state.reload}/>
    {!state.loading && !state.error && !state.data?.length && <p>Сохранённых версий пока нет.</p>}
    {!state.loading && state.data?.map(v => <article className="history-row" key={v.id}><div><strong>{dateLabel(v.created_at)}</strong><p>Версия {v.id.slice(0, 8)}</p></div><ProtocolExport meetingId={meetingId} versionId={v.id} available/></article>)}
    <div className="meeting-actions"><button className="secondary-button" disabled={offset === 0 || state.loading} onClick={() => setOffset(offset - 50)}>Назад</button><button className="secondary-button" disabled={state.data?.length !== 50 || state.loading} onClick={() => setOffset(offset + 50)}>Далее</button></div>
  </section>
}
