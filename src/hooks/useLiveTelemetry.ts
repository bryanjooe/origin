import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { TelemetryPoint } from '../types/domain'

const MAX_POINTS = 360
const POLL_MS = 1_000

export function useLiveTelemetry(enabled = true) {
  const [points, setPoints] = useState<TelemetryPoint[]>([])
  const [stream, setStream] = useState<'polling' | 'unavailable'>('polling')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    let timer: number | undefined
    let cursor = -1
    let runId: string | undefined
    let busy = false

    const poll = async () => {
      if (busy || stopped) return
      busy = true
      try {
        const batch = await api.getTelemetry(cursor, cursor < 0 ? MAX_POINTS : 200)
        if (!stopped) {
          const rows = batch.items
          if (runId && batch.run_id !== runId) {
            cursor = -1
            setPoints([])
          }
          runId = batch.run_id
          if (rows.length) {
            cursor = Math.max(cursor, ...rows.map((row) => typeof row.tick === 'number' ? row.tick : -1))
            setPoints((current) => [...current, ...rows].slice(-MAX_POINTS))
          }
          setError(null)
          setStream('polling')
        }
      } catch (caught) {
        if (!stopped) {
          setError(caught instanceof Error ? caught.message : 'Telemetry is unavailable.')
          setStream('unavailable')
        }
      } finally { busy = false }
    }

    void poll()
    timer = window.setInterval(() => void poll(), POLL_MS)
    return () => { stopped = true; if (timer !== undefined) window.clearInterval(timer) }
  }, [enabled])

  return { points, stream, error }
}
