import type { AnalysisDetails } from './liveApi'

export function AnalysisNotes({ details }: { details?: AnalysisDetails | null }) {
  if (!details) return null
  return <section className="panel live-form">
    <h2>Результаты анализа</h2>
    {details.review_required && <p role="status">Есть пункты для проверки. Уточните имена участников и сроки поручений перед использованием протокола.</p>}
    {details.topics.length > 0 && <div><h3>Темы</h3><ul>{details.topics.map((s, i) => <li key={i}>{s}</li>)}</ul></div>}
    {details.key_points.length > 0 && <div><h3>Ключевые факты</h3><ul>{details.key_points.map((s, i) => <li key={i}>{s}</li>)}</ul></div>}
    {details.unresolved_questions.length > 0 && <div><h3>Требуют уточнения</h3><ul>{details.unresolved_questions.map((s, i) => <li key={i}>{s}</li>)}</ul></div>}
    {details.review_issues.length > 0 && <details><summary>Замечания к протоколу ({details.review_issues.length})</summary><ul>{details.review_issues.map((s, i) => <li key={i}>{s.reason}</li>)}</ul></details>}
  </section>
}
