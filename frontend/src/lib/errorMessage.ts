const messages: Record<string, string> = {
  meeting_agent_invalid_output: 'ИИ не смог сформировать подтверждённый результат. Запись сохранена; повторите обработку.',
  processing_not_configured: 'Обработка не настроена на сервере. Проверьте настройки распознавания и анализа.',
  meeting_intelligence_not_configured: 'На сервере не настроен ИИ-анализ. Проверьте API-ключ и модели.',
  meeting_analysis_busy: 'Сервер занят анализом другой записи. Повторите через несколько минут.',
  meeting_analysis_budget_exceeded: 'Запись превышает установленный лимит анализа. Требуется увеличить лимит на сервере.',
  meeting_protocol_not_ready: 'Протокол ещё не готов. Дождитесь завершения анализа.',
  meeting_extraction_failed: 'Не удалось получить результат от сервиса анализа. Повторите обработку.',
  meeting_resolution_failed: 'Не удалось согласовать решения и поручения. Повторите обработку.',
  meeting_summary_failed: 'Не удалось сформировать саммари. Повторите обработку.',
  meeting_review_failed: 'Не удалось проверить протокол. Повторите обработку.',
}
export function errorMessage(code: string | null | undefined, fallback: string): string {
  return (code && messages[code]) || fallback
}
