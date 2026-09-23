import type { PropsWithChildren } from 'react'

export function AppShell({ children }: PropsWithChildren) {
  return <><nav className="navbar bg-white border-bottom"><div className="container py-2">
    <a href="/" className="navbar-brand fw-bold">✳ SuperPuperNova</a>
    <span className="badge text-bg-light border">Прототип / 0.1</span>
  </div></nav><main className="container py-5">{children}</main></>
}
