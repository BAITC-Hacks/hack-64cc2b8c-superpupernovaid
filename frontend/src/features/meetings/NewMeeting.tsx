import { useRef, useState } from 'react'
import { Icon } from '../../components/ui/Icon'
import { meetingMediaApi, meetingsApi } from './api'
import { liveApi } from './liveApi'

type Stage = 'form' | 'uploading' | 'ready'

export function NewMeeting({ onOpenMeeting }: { onOpenMeeting: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [stage, setStage] = useState<Stage>('form')
  const [error, setError] = useState('')
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [language, setLanguage] = useState<'ru' | 'kk' | 'mixed'>('ru')
  const [participantCount, setParticipantCount] = useState(5)
  const [consent, setConsent] = useState(false)
  const meetingRef = useRef<string | null>(null)
  const assetRef = useRef<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const selectFile = (next?: File) => {
    if (!next || stage === 'uploading') return
    if (!next.size || next.size > 2 * 1024 ** 3) { setError('Выберите непустую запись размером до 2 ГБ.'); return }
    setFile(next)
    meetingRef.current = null
    assetRef.current = null
    setError('')
  }

  const start = async () => {
    if (!file || !consent || !title.trim()) return
    setStage('uploading')
    setError('')
    try {
      if (!meetingRef.current) {
        const meeting = await meetingsApi.create({
          title, scheduled_at: date ? new Date(`${date}T00:00:00`).toISOString() : null,
          language_hint: language, expected_participant_count: participantCount,
          recording_consent_confirmed: consent,
        })
        meetingRef.current = meeting.id
      }
      if (!assetRef.current) {
        const asset = await meetingMediaApi.upload(meetingRef.current, file)
        assetRef.current = asset.id
      }
      await liveApi.process(meetingRef.current, assetRef.current)
      setStage('ready')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось загрузить запись')
      setStage('form')
    }
  }

  if (stage === 'ready') return <section className="success-screen panel">
    <span className="success-mark"><Icon name="check" size={38}/></span>
    <p className="eyebrow">ЗАПИСЬ ПРИНЯТА</p><h1>Обработка запущена</h1>
    <p>Запись поставлена в очередь. Откройте совещание, чтобы следить за обработкой, прочитать результат и скачать протокол.</p>
    <div className="pipeline"><span className="done">Загрузка</span><i/><span>Подготовка аудио</span><i/><span>Распознавание</span><i/><span>Протокол</span></div>
    <button className="primary-button" onClick={() => meetingRef.current && onOpenMeeting(meetingRef.current)}>Открыть рабочее пространство <Icon name="arrow" size={17}/></button>
  </section>

  return <>
    <section className="page-heading"><div><p className="eyebrow">НОВАЯ ОБРАБОТКА</p><h1>Добавить совещание</h1><p>Аудио передаётся в NVIDIA Cloud, текст — настроенному на сервере ИИ для подготовки протокола.</p></div></section>
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
          <label><span>Название совещания</span><input maxLength={255} placeholder="Например, планирование запуска" value={title} onChange={event => { setTitle(event.target.value); meetingRef.current = null; assetRef.current = null }} disabled={stage === 'uploading'} /></label>
          <label><span>Дата</span><div className="input-with-icon"><Icon name="calendar" size={18}/><input type="date" value={date} disabled={stage === 'uploading'} onChange={event => { setDate(event.target.value); meetingRef.current = null; assetRef.current = null }} /></div></label>
          <label><span>Язык записи</span><select value={language} disabled={stage === 'uploading'} onChange={event => { setLanguage(event.target.value as typeof language); meetingRef.current = null; assetRef.current = null }}><option value="ru">Русский</option><option value="mixed">Русский + Қазақша (распознавание не поддержано)</option><option value="kk">Қазақша (распознавание не поддержано)</option></select></label>
          <label><span>Ожидается участников</span><input type="number" min="1" max="1000" value={participantCount} disabled={stage === 'uploading'} onChange={event => { setParticipantCount(Number(event.target.value)); meetingRef.current = null; assetRef.current = null }} /></label>
        </div>
        <label className="consent"><input type="checkbox" checked={consent} disabled={stage === 'uploading'} onChange={event => { setConsent(event.target.checked); meetingRef.current = null; assetRef.current = null }}/><span><strong>Участники уведомлены о записи</strong><small>Подтверждаю наличие согласия на запись и автоматическую транскрибацию.</small></span></label>
        {error && <div className="form-error"><Icon name="warning"/> <span><strong>Не удалось запустить обработку</strong>{error}. Запись, если уже загружена, сохранена. Повторите запуск после устранения ошибки.</span></div>}
        {meetingRef.current && stage === 'form' && <button className="text-button" onClick={() => onOpenMeeting(meetingRef.current!)}>Открыть созданное совещание</button>}
        <div className="form-actions"><span><Icon name="lock" size={17}/> Обработка речи — NVIDIA Cloud</span><button className="primary-button" disabled={!file || !consent || !title.trim() || language !== 'ru' || (!Number.isInteger(participantCount) || participantCount < 1 || participantCount > 1000) || stage === 'uploading'} onClick={start}>{stage === 'uploading' ? <><span className="spinner-border spinner-border-sm"/> Загружаем…</> : <>Начать обработку <Icon name="arrow" size={17}/></>}</button></div>
      </section>
      <aside className="process-aside">
        <h3>Что произойдёт дальше</h3>
        <ol><li><span><Icon name="file"/></span><div><strong>Подготовка аудио</strong><p>Проверка и приведение записи к единому формату.</p></div></li><li><span><Icon name="language"/></span><div><strong>Распознавание речи</strong><p>Сейчас поддержано облачное распознавание русского.</p></div></li><li><span><Icon name="users"/></span><div><strong>Разделение спикеров</strong><p>Реплики будут сгруппированы по участникам.</p></div></li><li><span><Icon name="spark"/></span><div><strong>Готовый протокол</strong><p>Саммари, решения и поручения со сроками.</p></div></li></ol>
        <div className="aside-note"><Icon name="shield"/><div><strong>Режим обработки</strong><p>Распознавание использует NVIDIA Cloud. Доступ к записям требует защиты перед внешним развёртыванием.</p></div></div>
      </aside>
    </div>
  </>
}
