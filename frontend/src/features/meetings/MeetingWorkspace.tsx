import { useState } from 'react'
import { Icon } from '../../components/ui/Icon'
import { tasks, transcript } from './data'

type Tab = 'summary' | 'transcript' | 'tasks'

export function MeetingWorkspace() {
  const [tab, setTab] = useState<Tab>('summary')
  const [toast, setToast] = useState('')

  const exportProtocol = (format: 'PDF' | 'DOCX') => {
    const content = `ПРОТОКОЛ СОВЕЩАНИЯ\nПланирование запуска Q4\n23 сентября 2026\n\nКлючевые решения:\n- Пилотный запуск запланирован на 1 октября.\n- Инфраструктура разворачивается в закрытом контуре.\n- Первая группа — 20 пользователей.\n\nПоручения:\n${tasks.slice(0, 3).map(item => `- ${item.text} — ${item.owner}, ${item.due}`).join('\n')}`
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `protocol-q4.${format.toLowerCase()}.txt`
    link.click()
    URL.revokeObjectURL(link.href)
    setToast(`Черновик для ${format} подготовлен`)
    window.setTimeout(() => setToast(''), 2500)
  }

  return <>
    {toast && <div className="toast-note"><Icon name="check" size={17}/>{toast}</div>}
    <section className="meeting-header">
      <div><div className="breadcrumb">Совещания <Icon name="arrow" size={14}/> 23 сентября</div><h1>Планирование запуска Q4</h1><p><Icon name="calendar" size={16}/> 23 сентября 2026, 10:00 <i/> <Icon name="clock" size={16}/> 48 минут <i/> <Icon name="users" size={16}/> 6 участников</p></div>
      <div className="meeting-actions"><button className="secondary-button"><Icon name="edit" size={17}/> Редактировать</button><div className="export-group"><button onClick={() => exportProtocol('PDF')}><Icon name="download" size={17}/> Экспорт</button><button className="export-caret" onClick={() => exportProtocol('DOCX')} aria-label="Экспорт DOCX"><Icon name="chevron" size={15}/></button></div></div>
    </section>

    <section className="processing-banner"><div className="processing-copy"><span><Icon name="spark"/></span><div><strong>Протокол готов</strong><p>Обработка завершена за 7 мин 24 сек · язык: русский + қазақша</p></div></div><div className="confidence"><span>Точность распознавания</span><strong>94%</strong><div><i/></div></div></section>

    <div className="workspace-tabs" role="tablist">
      <button className={tab === 'summary' ? 'active' : ''} onClick={() => setTab('summary')}>Саммари</button>
      <button className={tab === 'transcript' ? 'active' : ''} onClick={() => setTab('transcript')}>Транскрипт <span>248</span></button>
      <button className={tab === 'tasks' ? 'active' : ''} onClick={() => setTab('tasks')}>Поручения <span>5</span></button>
    </div>

    {tab === 'summary' && <div className="summary-layout">
      <div className="summary-main">
        <section className="panel summary-card"><div className="card-title"><span className="title-icon purple"><Icon name="spark"/></span><div><p className="eyebrow">СФОРМИРОВАНО ИИ</p><h2>Краткое содержание</h2></div><button className="icon-button"><Icon name="edit" size={18}/></button></div><p>Команда согласовала план пилотного запуска системы автопротоколирования на 1 октября. Основное внимание уделили готовности закрытого контура, составу пилотной группы и интеграции с внутренней СЭД.</p><p>Инфраструктура будет подготовлена до конца недели. В пилот войдут 20 сотрудников из трёх подразделений. По итогам двухнедельного теста команда соберёт обратную связь и примет решение о масштабировании.</p></section>
        <section className="panel decision-card"><div className="card-title"><span className="title-icon green"><Icon name="check"/></span><div><h2>Ключевые решения</h2><p>3 решения зафиксировано</p></div></div><ul><li><span>01</span><div><strong>Запустить пилот 1 октября</strong><p>Первый этап рассчитан на две недели и 20 пользователей.</p></div></li><li><span>02</span><div><strong>Развернуть систему в закрытом контуре</strong><p>Без передачи записей и транскриптов во внешние сервисы.</p></div></li><li><span>03</span><div><strong>Интеграцию с СЭД вынести во второй этап</strong><p>После проверки качества распознавания и сценариев экспорта.</p></div></li></ul></section>
      </div>
      <aside className="summary-aside">
        <section className="panel"><div className="panel-head"><div><h2>Участники</h2><p>6 спикеров определено</p></div><button className="icon-button"><Icon name="edit" size={17}/></button></div><div className="speaker-list">{['Айдана С.|АС|26%', 'Марат К.|МК|22%', 'Руслан Т.|РТ|18%', 'Динара А.|ДА|15%'].map((line, index) => { const [name, initials, share] = line.split('|'); return <div key={name}><span className={`speaker-avatar c${index}`}>{initials}</span><span><strong>{name}</strong><small>{share} речи</small></span><div className="speaker-bar"><i style={{ width: share }}/></div></div>})}</div><button className="wide-text-button">Показать всех участников</button></section>
        <section className="panel recording-card"><div className="waveform"><button><Icon name="play" size={24}/></button><div className="bars">{[12,22,14,31,20,38,24,14,34,27,18,40,24,31,16,28,20,36,14,25,18,33,21,29,15,24].map((height, index) => <i key={index} style={{ height }}/>)}</div></div><div><strong>00:00</strong><span>48:12</span></div><p>meeting_23_sep.mp4 · 186 МБ</p></section>
      </aside>
    </div>}

    {tab === 'transcript' && <section className="panel transcript-card"><div className="transcript-tools"><div><h2>Транскрипт</h2><p>Нажмите на реплику, чтобы перейти к фрагменту записи.</p></div><label><Icon name="search" size={17}/><input placeholder="Поиск по тексту"/></label></div><div className="transcript-list">{transcript.map(item => <button key={item.time} className="transcript-row"><span className="timecode">{item.time}</span><span className="speaker-avatar" style={{ background: item.color }}>{item.initials}</span><span><strong>{item.speaker}</strong><p>{item.text}</p></span><Icon name="play" size={18}/></button>)}</div></section>}

    {tab === 'tasks' && <section className="panel embedded-tasks"><div className="panel-head"><div><h2>Поручения совещания</h2><p>Проверьте ответственных и сроки перед рассылкой.</p></div><button className="secondary-button"><Icon name="plus" size={17}/> Добавить</button></div>{tasks.map(task => <article key={task.id}><button className={`task-check ${task.status === 'Выполнено' ? 'checked' : ''}`}><Icon name="check" size={15}/></button><div><strong>{task.text}</strong><p>{task.meeting}</p></div><span className="mini-avatar">{task.initials}</span><span>{task.owner}</span><span className={task.status === 'Просрочено' ? 'due overdue' : 'due'}>{task.due}</span><button className="icon-button"><Icon name="dots"/></button></article>)}</section>}
  </>
}
