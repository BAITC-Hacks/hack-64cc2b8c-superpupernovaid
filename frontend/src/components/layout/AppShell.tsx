import type { PropsWithChildren } from 'react'
import { Icon } from '../ui/Icon'

export type AppView = 'dashboard' | 'new' | 'meeting' | 'tasks' | 'notifications'

type Props = PropsWithChildren<{ view: AppView; onNavigate: (view: AppView) => void; demo: boolean }>

const navItems: { id: AppView; label: string; icon: 'grid' | 'mic' | 'check' }[] = [
  { id: 'dashboard', label: 'Обзор', icon: 'grid' },
  { id: 'meeting', label: 'Совещания', icon: 'mic' },
  { id: 'tasks', label: 'Поручения', icon: 'check' },
]

export function AppShell({ children, view, onNavigate, demo }: Props) {
  return <div className="app-frame">
    <aside className="sidebar">
      <button className="brand" onClick={() => onNavigate('dashboard')} aria-label="На главную">
        <span className="brand-mark"><span /></span>
        <span><strong>Qoryt</strong><small>AI-протокол</small></span>
      </button>
      <nav className="side-nav" aria-label="Основная навигация">
        {navItems.map(item => <button key={item.id} className={view === item.id || (view === 'new' && item.id === 'meeting') ? 'active' : ''} onClick={() => onNavigate(item.id)}>
          <Icon name={item.icon} />{item.label}
        </button>)}
      </nav>
      <div className="privacy-card">
        <span className="privacy-icon"><Icon name="shield" /></span>
        <strong>Обработка записи</strong>
        <p>Распознавание речи использует NVIDIA Cloud.</p>
      </div>
      <div className="user-card">
        <span className="avatar">Q</span><span><strong>Qoryt</strong><small>Рабочее пространство</small></span>
      </div>
    </aside>
    <div className="main-column">
      <header className="topbar">
        <div className="mobile-brand"><span className="brand-mark"><span /></span><strong>Qoryt</strong></div>
        <div className="top-status">{demo ? 'Демо-режим' : 'Рабочее пространство'}</div>
        <div className="top-actions"><button className="icon-button" aria-label="Уведомления" aria-pressed={view === 'notifications'} onClick={() => onNavigate('notifications')}><Icon name="bell" /></button></div>
      </header>
      <main className="page-content">{children}</main>
      <nav className="mobile-nav" aria-label="Мобильная навигация">
        {navItems.map(item => <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => onNavigate(item.id)}><Icon name={item.icon} /><span>{item.label}</span></button>)}
        <button className={view === 'new' ? 'active' : ''} onClick={() => onNavigate('new')}><Icon name="plus" /><span>Запись</span></button>
      </nav>
    </div>
  </div>
}
