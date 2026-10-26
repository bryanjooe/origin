import { useCallback, useEffect, useRef, useState } from 'react'

export interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

export function useApiResource<T>(
  key: string,
  loader: () => Promise<T>,
  refreshMs?: number,
  enabled = true,
): ResourceState<T> {
  const loaderRef = useRef(loader)
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<string | null>(null)
  const [reloadCount, setReloadCount] = useState(0)
  const dataRef = useRef<T | null>(null)

  loaderRef.current = loader

  const reload = useCallback(() => setReloadCount((count) => count + 1), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    let active = true
    const load = async () => {
      setLoading(dataRef.current === null)
      try {
        const next = await loaderRef.current()
        if (!active) return
        dataRef.current = next
        setData(next)
        setError(null)
      } catch (caught) {
        if (!active) return
        setError(caught instanceof Error ? caught.message : 'Unable to load this data.')
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    const timer = refreshMs ? window.setInterval(() => void load(), refreshMs) : undefined
    return () => {
      active = false
      if (timer) window.clearInterval(timer)
    }
    // The loader is kept in a ref so callers can pass inline request functions safely.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, refreshMs, reloadCount])

  return { data, loading, error, reload }
}
