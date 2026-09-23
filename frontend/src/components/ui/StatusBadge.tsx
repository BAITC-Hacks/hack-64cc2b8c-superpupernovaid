import type { JobStatus } from '../../features/jobs/api'
const labels: Record<JobStatus, string> = { queued: 'В очереди', running: 'В работе', succeeded: 'Готово', failed: 'Ошибка' }
const colors: Record<JobStatus, string> = { queued: 'secondary', running: 'primary', succeeded: 'success', failed: 'danger' }

export function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`badge text-bg-${colors[status]}`}>{labels[status]}</span>
}
