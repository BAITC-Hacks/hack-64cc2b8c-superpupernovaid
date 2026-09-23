import { useRef, useState } from 'react'
import { Icon } from '../../components/ui/Icon'
import { meetingMediaApi } from './api'

type Stage = 'form' | 'uploading' | 'ready'

export function NewMeeting({ onOpenMeeting }: { onOpenMeeting: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [stage, setStage] = useState<Stage>('form')
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const selectFile = (next?: File) => {
    if (!next) return
    setFile(next)
    setError('')
  }

  const start = async () => {
    if (!file) return
    setStage('uploading')
    setError('')
    try {
      const meetingId = crypto.randomUUID()
      const asset = await meetingMediaApi.upload(meetingId, file)
      await meetingMediaApi.preprocess(meetingId, asset.id)
      setStage('ready')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить запись')
      setStage('form')
    }
  }

  if (stage === 'ready') return <section className="success-screen panel">
    <span className="success-mark"><Icon name="check" size={38}/></span>
    <p className="eyebrow">ЗАПИСЬ ПРИНЯТА</p><h1>Подготовка началась</h1>
    <p>Аудио нормализовано и готово к локальной обработке. Экран протокола показывает структуру следующего этапа.</p>
    <div className="pipeline"><span className="done">Загрузка</span><i/><span className="done">Подготовка аудио</span><i/><span>Распознавание</span><i/><span>Протокол</span></div>
    <button className="primary-button" onClick={onOpenMeeting}>Открыть рабочее пространство <Icon name="arrow" size={17}/></button>
  </section>

  return <>
    <section className="page-heading"><div><p className="eyebrow">НОВАЯ ОБРАБОТКА</p><h1>Добавить совещание</h1><p>Запись останется внутри защищённого контура.</p></div></section>
    <div className="form-layout">
      <section className="panel upload-panel">
        <div className="section-number"><span>1</span><div><h2>Запись совещания</h2><p>Поддерживаются MP3, WAV, M4A, MP4, MOV и MKV</p></div></div>
        <div className={`dropzone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`} onDragOver={event => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); selectFile(event.dataTransfer.files[0]) }}>
          <input ref={inputRef} type="file" accept="audio/*,video/*,.mkv" onChange={event => selectFile(event.target.files?.[0])} hidden />
          <span className="drop-icon"><Icon name={file ? 'file' : 'upload'} size={28}/></span>
          {file ? <><strong>{file.name}</strong><p>{(file.size / 1024 / 1024).toFixed(1)} МБ · готов к загрузке</p><button className="text-button" onClick={() => inputRef.current?.click()}>Выбрать другой файл</button></> : <><strong>Перетащите запись сюда</strong><p>или выберите файл на компьютере · до 2 ГБ</p><button className="secondary-button" onClick={() => inputRef.current?.click()}>Выбрать файл</button></>}
        </div>

        <div className="section-number form-section"><span>2</span><div><h2>Параметры</h2><p>Помогут точнее подготовить протокол</p></div></div>
        <div className="field-grid">
          <label><span>Название совещания</span><input defaultValue="Планирование запуска Q4" /></label>
          <label><span>Дата</span><div className="input-with-icon"><Icon name="calendar" size={18}/><input type="date" defaultValue="2026-09-23" /></div></label>
          <label><span>Язык записи</span><select defaultValue="mixed"><option value="mixed">Русский + Қазақша</option><option>Русский</option><option>Қазақша</option></select></label>
          <label><span>Ожидается участников</span><select defaultValue="6"><option>2–4</option><option value="6">5–8</option><option>9 и более</option></select></label>
        </div>
        <label className="consent"><input type="checkbox" defaultChecked/><span><strong>Участники уведомлены о записи</strong><small>Подтверждаю наличие согласия на запись и автоматическую транскрибацию.</small></span></label>
        {error && <div className="form-error"><Icon name="warning"/> <span><strong>Загрузка не завершена</strong>{error}. Убедитесь, что локальный API запущен.</span></div>}
        <div className="form-actions"><span><Icon name="lock" size={17}/> Данные не покидают контур</span><button className="primary-button" disabled={!file || stage === 'uploading'} onClick={start}>{stage === 'uploading' ? <><span className="spinner-border spinner-border-sm"/> Загружаем…</> : <>Начать обработку <Icon name="arrow" size={17}/></>}</button></div>
      </section>
      <aside className="process-aside">
        <h3>Что произойдёт дальше</h3>
        <ol><li><span><Icon name="file"/></span><div><strong>Подготовка аудио</strong><p>Проверка и приведение записи к единому формату.</p></div></li><li><span><Icon name="language"/></span><div><strong>Распознавание речи</strong><p>Русский, казахский и смешанная речь.</p></div></li><li><span><Icon name="users"/></span><div><strong>Разделение спикеров</strong><p>Реплики будут сгруппированы по участникам.</p></div></li><li><span><Icon name="spark"/></span><div><strong>Готовый протокол</strong><p>Саммари, решения и поручения со сроками.</p></div></li></ol>
        <div className="aside-note"><Icon name="shield"/><div><strong>Приватность по умолчанию</strong><p>Модели развёрнуты локально. Записи не передаются во внешние AI API.</p></div></div>
      </aside>
    </div>
  </>
}
