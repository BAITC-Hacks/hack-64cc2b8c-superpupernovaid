import { useMemo, useState } from 'react'
import { Icon } from '../../components/ui/Icon'
import { tasks as initialTasks, type TaskStatus } from '../meetings/data'

type Filter = 'Все' | TaskStatus

export function TaskBoard() {
  const [tasks, setTasks] = useState(initialTasks)
  const [filter, setFilter] = useState<Filter>('Все')
  const visible = useMemo(() => filter === 'Все' ? tasks : tasks.filter(task => task.status === filter), [tasks, filter])

  const toggle = (id: string) => setTasks(current => current.map(task => task.id === id ? { ...task, status: task.status === 'Выполнено' ? 'В работе' : 'Выполнено' as TaskStatus } : task))

  return <>
    <section className="page-heading"><div><p className="eyebrow">КОНТРОЛЬ ИСПОЛНЕНИЯ</p><h1>Поручения</h1><p>Все договорённости из протоколов в одном месте.</p></div><button className="primary-button"><Icon name="plus"/> Добавить поручение</button></section>
    <section className="task-stats"><article><span className="purple-dot"/><div><strong>{tasks.filter(t => t.status === 'В работе').length}</strong><small>В работе</small></div></article><article><span className="red-dot"/><div><strong>{tasks.filter(t => t.status === 'Просрочено').length}</strong><small>Просрочено</small></div></article><article><span className="green-dot"/><div><strong>{tasks.filter(t => t.status === 'Выполнено').length}</strong><small>Выполнено</small></div></article><article><span className="amber-dot"/><div><strong>2</strong><small>Срок на неделе</small></div></article></section>
    <section className="panel tasks-panel">
      <div className="task-toolbar"><div className="filter-tabs">{(['Все', 'В работе', 'Просрочено', 'Выполнено'] as Filter[]).map(item => <button key={item} className={filter === item ? 'active' : ''} onClick={() => setFilter(item)}>{item}{item === 'Все' && <span>{tasks.length}</span>}</button>)}</div><div className="toolbar-actions"><label><Icon name="search" size={17}/><input placeholder="Найти поручение"/></label><button className="secondary-button"><Icon name="filter" size={17}/> Фильтры</button></div></div>
      <div className="task-table" role="table">
        <div className="task-table-head" role="row"><span>Поручение</span><span>Ответственный</span><span>Срок</span><span>Статус</span><span/></div>
        {visible.map(task => <div className="task-table-row" role="row" key={task.id}>
          <div className="task-description"><button className={`task-check ${task.status === 'Выполнено' ? 'checked' : ''}`} onClick={() => toggle(task.id)} aria-label="Изменить статус"><Icon name="check" size={15}/></button><span><strong>{task.text}</strong><small>{task.meeting} · {task.id}</small></span></div>
          <div className="task-owner"><span className="mini-avatar">{task.initials}</span>{task.owner}</div>
          <div className={task.status === 'Просрочено' ? 'task-date overdue' : 'task-date'}><Icon name="calendar" size={16}/>{task.due}</div>
          <div><span className={`task-status status-${task.status.toLowerCase().replace(' ', '-')}`}>{task.status}</span></div>
          <button className="icon-button"><Icon name="dots"/></button>
        </div>)}
      </div>
      {visible.length === 0 && <div className="empty-filter"><Icon name="check" size={28}/><strong>Здесь пока пусто</strong><p>Поручений с таким статусом нет.</p></div>}
    </section>
  </>
}
