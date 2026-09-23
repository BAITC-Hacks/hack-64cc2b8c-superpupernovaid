import { useEffect, useState } from 'react'

export function useRemote<T>(load: () => Promise<T>, pollMs = 0, pollWhen?: (value: T) => boolean) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    setLoading(true)
    const run = async () => {
      let repeat = true
      try { const value = await load(); repeat = pollWhen?.(value) ?? true; if (active) { setData(value); setError('') } }
      catch (e) { if (active) setError(e instanceof Error ? e.message : 'Не удалось получить данные') }
      finally { if (active) { setLoading(false); if (pollMs && repeat) timer = setTimeout(run, pollMs) } }
    }
    void run()
    return () => { active = false; clearTimeout(timer) }
  }, [load, pollMs, revision, pollWhen])
  return { data, error, loading, reload: () => setRevision(n => n + 1) }
}

export function RemoteState({ loading, error, retry }: { loading: boolean; error: string; retry: () => void }) {
  return <>{loading && <p role="status">Загружаем данные…</p>}{error && <div className="form-error" role="alert"><span>{error}</span><button className="secondary-button" onClick={retry}>Повторить</button></div>}</>
}
