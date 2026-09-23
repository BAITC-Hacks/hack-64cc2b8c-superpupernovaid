import { useState } from 'react'
import { AppShell, type AppView } from './components/layout/AppShell'
import { Dashboard } from './features/meetings/Dashboard'
import { MeetingWorkspace } from './features/meetings/MeetingWorkspace'
import { NewMeeting } from './features/meetings/NewMeeting'
import { TaskBoard } from './features/tasks/TaskBoard'

export function App() {
  const [view, setView] = useState<AppView>('dashboard')

  const navigate = (next: AppView) => {
    setView(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return <AppShell view={view} onNavigate={navigate}>
    {view === 'dashboard' && <Dashboard onNavigate={navigate} />}
    {view === 'new' && <NewMeeting onOpenMeeting={() => navigate('meeting')} />}
    {view === 'meeting' && <MeetingWorkspace />}
    {view === 'tasks' && <TaskBoard />}
  </AppShell>
}
