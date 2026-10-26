import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from '../services/api'
import type { IncidentList, LiveData, Scenario, State, Sustainability, SystemEvent, TelemetryPoint } from '../types'

export function mergePoints(previous: TelemetryPoint[], incoming: TelemetryPoint[], changedRun: boolean) {
  const rows = new Map((changedRun ? [] : previous).map(point => [point.telemetry.tick, point]))
  incoming.forEach(point => rows.set(point.telemetry.tick, point))
  return [...rows.values()].sort((a, b) => a.telemetry.tick - b.telemetry.tick).slice(-240)
}

export function useLiveData() {
  const [data, setData] = useState<LiveData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [revision, setRevision] = useState(0)
  const cache = useRef<LiveData | null>(null)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const state = await get<State>('/system/state', controller.signal)
        const previous = cache.current
        const changed = previous?.state.run_id !== state.run_id
        const cursor = changed ? Math.max(-1, state.next_tick - 241) : previous?.points.at(-1)?.telemetry.tick ?? -1
        const eventCursor = changed ? 0 : previous?.events.at(-1)?.id ?? 0
        const run = encodeURIComponent(state.run_id)
        const [telemetry, events, sustainability, incidents, scenario] = await Promise.all([
          get<{ items: TelemetryPoint[] }>(`/telemetry?run_id=${run}&after_tick=${cursor}&limit=300`, controller.signal),
          get<{ items: SystemEvent[] }>(`/events?run_id=${run}&after_id=${eventCursor}&limit=2000`, controller.signal),
          get<Sustainability>('/metrics/sustainability', controller.signal),
          get<IncidentList>(`/incidents?run_id=${run}&limit=100`, controller.signal),
          get<Scenario>('/simulation/scenario', controller.signal),
        ])
        if (controller.signal.aborted) return
        // A reset from another client during polling must not mix run histories.
        if (sustainability.run_id !== state.run_id || scenario.id !== state.run_id) return
        const next = { state, points: mergePoints(previous?.points ?? [], telemetry.items.filter(point => point.telemetry.tick < state.next_tick), changed),
          events: [...(changed ? [] : previous?.events ?? []), ...events.items].slice(-40), sustainability, incidents, scenario }
        cache.current = next; setData(next); setError(null); setUpdatedAt(Date.now())
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Unable to reach the backend')
      } finally { if (!controller.signal.aborted) timer = setTimeout(poll, 1000) }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [revision])
  return { data, error, updatedAt, refresh, revision }
}

export function useResource<T>(path: string | null, revision = 0, interval = 3000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    setData(null); setError(null)
    if (!path) return
    async function poll() {
      try { const value = await get<T>(path!, controller.signal); if (!controller.signal.aborted) { setData(previous => JSON.stringify(previous) === JSON.stringify(value) ? previous : value); setError(null) } }
      catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Request failed') }
      finally { if (!controller.signal.aborted && interval > 0) timer = setTimeout(poll, interval) }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [path, revision, interval])
  return { data, error }
}

export function useAction(refresh: () => void) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(false)
  const act = async (path: string, body?: unknown, success = 'Simulation updated') => {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(null); setMessage(null)
    try { await post(path, body); setMessage(success); refresh() }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'The operation failed'); refresh() }
    finally { pending.current = false; setBusy(false) }
  }
  return { act, busy, message, error }
}
