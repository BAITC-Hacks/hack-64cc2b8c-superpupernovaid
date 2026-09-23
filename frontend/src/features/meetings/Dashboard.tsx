import type { AppView } from '../../components/layout/AppShell'
import { Icon } from '../../components/ui/Icon'
import { meetings, tasks } from './data'

export function Dashboard({ onNavigate }: { onNavigate: (view: AppView) => void }) {
  return <>
    <section className="page-heading dashboard-heading">
      <div><p className="eyebrow">СРЕДА, 23 СЕНТЯБРЯ</p><h1>Доброе утро, Айдана</h1><p>У вас 2 поручения со сроком на этой неделе.</p></div>
      <button className="primary-button" onClick={() => onNavigate('new')}><Icon name="plus" /> Новое совещание</button>
    </section>

    <section className="stat-grid" aria-label="Сводка">
      <article className="stat-card featured"><span className="stat-icon"><Icon name="spark" /></span><div><small>Обработано совещаний</small><strong>12</strong><span>+3 за эту неделю</span></div></article>
      <article className="stat-card"><span className="stat-icon purple"><Icon name="check" /></span><div><small>Активные поручения</small><strong>8</strong><span>2 требуют внимания</span></div></article>
      <article className="stat-card"><span className="stat-icon amber"><Icon name="clock" /></span><div><small>Сэкономлено времени</small><strong>6,4 ч</strong><span>≈ 32 мин на протокол</span></div></article>
    </section>

    <section className="dashboard-grid">
      <div className="panel recent-panel">
        <div className="panel-head"><div><h2>Последние совещания</h2><p>Готовые протоколы и транскрипты</p></div><button className="text-button" onClick={() => onNavigate('meeting')}>Все совещания <Icon name="arrow" size={16} /></button></div>
        <div className="meeting-list">
          {meetings.map((meeting, index) => <button className="meeting-row" key={meeting.id} onClick={() => onNavigate('meeting')}>
            <span className="date-tile" style={{ '--accent': meeting.accent } as React.CSSProperties}><strong>{index === 0 ? '23' : index === 1 ? '22' : '18'}</strong><small>СЕН</small></span>
            <span className="meeting-main"><strong>{meeting.title}</strong><span><Icon name="clock" size={15}/>{meeting.date} · {meeting.duration} <i/> <Icon name="users" size={15}/>{meeting.people} участников</span></span>
            <span className="meeting-result"><span className="status-ready"><i/> {meeting.status}</span><small>{meeting.tasks} поручений</small></span>
            <Icon name="arrow" />
          </button>)}
        </div>
      </div>

      <div className="panel attention-panel">
        <div className="panel-head"><div><h2>Требуют внимания</h2><p>Ближайшие сроки</p></div><span className="counter">2</span></div>
        <div className="attention-list">
          {tasks.slice(0, 2).map((task, index) => <article key={task.id} className={index === 0 ? 'urgent' : ''}>
            <div className="attention-meta"><span>{index === 0 ? 'СЕГОДНЯ' : 'ЗАВТРА'}</span><small>{task.due}</small></div>
            <h3>{task.text}</h3>
            <div className="owner-line"><span className="mini-avatar">{task.initials}</span>{task.owner}<button aria-label="Открыть поручение"><Icon name="arrow" size={17}/></button></div>
          </article>)}
        </div>
        <button className="wide-text-button" onClick={() => onNavigate('tasks')}>Открыть все поручения</button>
      </div>
    </section>

    <section className="quick-start">
      <div className="quick-copy"><span className="quick-icon"><Icon name="upload" /></span><div><h2>Есть запись совещания?</h2><p>Загрузите аудио или видео — система подготовит протокол, саммари и список поручений.</p></div></div>
      <button className="secondary-button" onClick={() => onNavigate('new')}>Загрузить запись <Icon name="arrow" size={17}/></button>
    </section>
  </>
}
