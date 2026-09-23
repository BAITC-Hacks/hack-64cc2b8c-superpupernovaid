import type { PropsWithChildren } from 'react'

export function AppCard({ title, children }: PropsWithChildren<{ title: string }>) {
  return <section className="card border-0 shadow-sm h-100"><div className="card-body p-4">
    <h2 className="h5 mb-4">{title}</h2>{children}
  </div></section>
}
