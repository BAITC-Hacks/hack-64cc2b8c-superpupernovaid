import { useRef, useState } from 'react'
import { ApiError } from '../../lib/http'
import { liveApi, type ExportFormat } from './liveApi'

export function ProtocolExport({ meetingId, available, versionId }: { meetingId: string; available: boolean; versionId?: string }) {
  const [format, setFormat] = useState<ExportFormat | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const pending = useRef(false)
  const download = async (next: ExportFormat) => {
    if (pending.current) return
    pending.current = true; setFormat(next); setMessage(''); setError('')
    try {
      const file = await liveApi.exportFile(meetingId, next, versionId)
      const url = URL.createObjectURL(file.blob)
      const link = document.createElement('a')
      link.href = url; link.download = file.filename
      document.body.appendChild(link); link.click(); link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60000)
      setMessage(`${next.toUpperCase()} передан для скачивания.`)
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 409 ? 'Протокол ещё не готов. Дождитесь завершения анализа.'
        : caught instanceof ApiError && caught.status === 429 ? 'Сервер занят другим экспортом. Повторите через несколько секунд.'
        : caught instanceof Error ? caught.message : 'Не удалось скачать протокол.')
    } finally { pending.current = false; setFormat(null) }
  }
  return <div className="protocol-export"><div className="meeting-actions">{(['pdf', 'docx'] as const).map(f => <button key={f} className="secondary-button" disabled={!available || format !== null} onClick={() => void download(f)}>{format === f ? 'Готовим файл…' : `Скачать ${f.toUpperCase()}`}</button>)}</div>{!available && <small>Экспорт доступен после сохранения анализа.</small>}{message && <p role="status">{message}</p>}{error && <p role="alert" className="form-error">{error}</p>}</div>
}
