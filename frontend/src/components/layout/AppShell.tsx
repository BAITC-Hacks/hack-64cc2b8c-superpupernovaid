import type { PropsWithChildren } from 'react'
import { Icon } from '../ui/Icon'

export type AppView = 'dashboard' | 'new' | 'meeting' | 'tasks'

type Props = PropsWithChildren<{ view: AppView; onNavigate: (view: AppView) => void }>

const navItems: { id: AppView; label: string; icon: 'grid' | 'mic' | 'check' }[] = [
  { id: 'dashboard', label: 'Обзор', icon: 'grid' },
  { id: 'meeting', label: 'Совещания', icon: 'mic' },
  { id: 'tasks', label: 'Поручения', icon: 'check' },
]

export function AppShell({ children, view, onNavigate }: Props) {
  return <div className="app-frame">
    <aside className="sidebar">
      <button className="brand" onClick={() => onNavigate('dashboard')} aria-label="На главную">
        <span className="brand-mark"><span /></span>
        <span><strong>Qoryt</strong><small>AI-протокол</small></span>
      </button>
      <nav className="side-nav" aria-label="Основная навигация">
        {navItems.map(item => <button key={item.id} className={view === item.id || (view === 'new' && item.id === 'meeting') ? 'active' : ''} onClick={() => onNavigate(item.id)}>
          <Icon name={item.icon} />{item.label}{item.id === 'tasks' && <span className="nav-count">5</span>}
        </button>)}
      </nav>
      <div className="privacy-card">
        <span className="privacy-icon"><Icon name="shield" /></span>
        <strong>Закрытый контур</strong>
        <p>Аудио и текст обрабатываются локально.</p>
        <span className="secure-state"><i /> Защищено</span>
      </div>
      <button className="user-card" aria-label="Профиль пользователя">
        <span className="avatar">АС</span><span><strong>Айдана С.</strong><small>Секретарь</small></span><Icon name="dots" />
      </button>
    </aside>
    <div className="main-column">
      <header className="topbar">
        <div className="mobile-brand"><span className="brand-mark"><span /></span><strong>Qoryt</strong></div>
        <div className="top-status"><span className="pulse-dot" /> Система готова к работе</div>
        <div className="top-actions"><button className="icon-button" aria-label="Поиск"><Icon name="search" /></button><button className="icon-button has-alert" aria-label="Уведомления"><Icon name="bell" /></button></div>
      </header>
      <main className="page-content">{children}</main>
      <nav className="mobile-nav" aria-label="Мобильная навигация">
        {navItems.map(item => <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => onNavigate(item.id)}><Icon name={item.icon} /><span>{item.label}</span></button>)}
        <button className={view === 'new' ? 'active' : ''} onClick={() => onNavigate('new')}><Icon name="plus" /><span>Запись</span></button>
      </nav>
    </div>
  </div>
}
