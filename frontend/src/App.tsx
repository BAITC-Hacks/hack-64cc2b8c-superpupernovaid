import { useEffect, useState } from 'react'
import { AppShell, type AppView } from './components/layout/AppShell'
import { Dashboard } from './features/meetings/Dashboard'
import { MeetingWorkspace } from './features/meetings/MeetingWorkspace'
import { NewMeeting } from './features/meetings/NewMeeting'
import { TaskBoard } from './features/tasks/TaskBoard'
import { LiveDashboard } from './features/meetings/LiveDashboard'
import { LiveWorkspace } from './features/meetings/LiveWorkspace'
import { LiveTasks } from './features/tasks/LiveTasks'
import { Notifications } from './features/tasks/Notifications'
import { parseRoute, routeHash, type Route } from './lib/navigation'

export function App() {
  const [{ view, demo, meetingId }, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const sync = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const go = (route: Route) => { window.location.hash = routeHash(route); setRoute(route); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  const openMeeting = (id: string) => go({ view: 'meeting', meetingId: id, demo: false })

  const navigate = (next: AppView) => {
    go({ view: next, meetingId: null, demo: next === 'notifications' ? false : demo })
  }

  return <AppShell view={view} onNavigate={navigate} demo={demo}>
    {view !== 'new' && <div className="data-mode"><span>{demo ? 'Демонстрационные данные' : 'Данные сервера'}</span><button className="text-button" onClick={() => go({ view: 'dashboard', demo: !demo, meetingId: null })}>{demo ? 'Подключить API' : 'Посмотреть демо'}</button></div>}
    {demo && view === 'dashboard' && <Dashboard onNavigate={navigate} />}
    {view === 'new' && <NewMeeting onOpenMeeting={openMeeting} />}
    {demo && view === 'meeting' && <MeetingWorkspace />}
    {demo && view === 'tasks' && <TaskBoard />}
    {!demo && (view === 'dashboard' || (view === 'meeting' && !meetingId)) && <LiveDashboard open={openMeeting} create={() => navigate('new')}/>}
    {!demo && view === 'meeting' && meetingId && <LiveWorkspace key={meetingId} meetingId={meetingId} back={() => navigate('meeting')}/>}
    {!demo && view === 'tasks' && <LiveTasks open={openMeeting}/>}
    {view === 'notifications' && <Notifications open={openMeeting}/>}
  </AppShell>
}
