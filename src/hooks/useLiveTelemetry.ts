import { useEffect, useState } from 'react'
import { api, telemetrySocketUrl } from '../services/api'
import type { TelemetryPoint } from '../types/domain'

const MAX_POINTS = 360
const POLL_MS = 3_000

type StreamState = 'connecting' | 'websocket' | 'polling' | 'unavailable'

function pointKey(point: TelemetryPoint): string {
  return String(point.tick ?? point.timestamp ?? point.time ?? point.simulation_time ?? JSON.stringify(point))
}

function mergePoints(current: TelemetryPoint[], incoming: TelemetryPoint[]): TelemetryPoint[] {
  const values = new Map(current.map((point) => [pointKey(point), point]))
  incoming.forEach((point) => values.set(pointKey(point), point))
  return [...values.values()].slice(-MAX_POINTS)
}

function decodeMessage(raw: string): TelemetryPoint[] {
  const parsed: unknown = JSON.parse(raw)
  if (Array.isArray(parsed)) return parsed as TelemetryPoint[]
  if (parsed && typeof parsed === 'object') {
    const record = parsed as { telemetry?: unknown; data?: unknown }
    if (Array.isArray(record.telemetry)) return record.telemetry as TelemetryPoint[]
    if (Array.isArray(record.data)) return record.data as TelemetryPoint[]
    return [parsed as TelemetryPoint]
  }
  return []
}

export function useLiveTelemetry(enabled = true) {
  const [points, setPoints] = useState<TelemetryPoint[]>([])
  const [stream, setStream] = useState<StreamState>('connecting')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    let socket: WebSocket | null = null
    let pollTimer: number | undefined
    let retryTimer: number | undefined
    let retryCount = 0

    const poll = async () => {
      try {
        const rows = await api.getTelemetry(MAX_POINTS)
        if (!stopped) {
          setPoints((current) => mergePoints(current, rows))
          setError(null)
          if (!socket || socket.readyState !== WebSocket.OPEN) setStream('polling')
        }
      } catch (caught) {
        if (!stopped) {
          setError(caught instanceof Error ? caught.message : 'Telemetry is unavailable.')
          if (!socket || socket.readyState !== WebSocket.OPEN) setStream('unavailable')
        }
      }
    }

    const startPolling = () => {
      if (pollTimer === undefined) pollTimer = window.setInterval(() => void poll(), POLL_MS)
    }

    const connect = () => {
      if (stopped || socket) return
      setStream(retryCount ? 'polling' : 'connecting')
      try {
        const activeSocket = new WebSocket(telemetrySocketUrl())
        socket = activeSocket
        activeSocket.onopen = () => {
          if (stopped || socket !== activeSocket) return
          retryCount = 0
          if (pollTimer !== undefined) window.clearInterval(pollTimer)
          pollTimer = undefined
          setStream('websocket')
          setError(null)
        }
        activeSocket.onmessage = (event) => {
          if (stopped || typeof event.data !== 'string') return
          try {
            setPoints((current) => mergePoints(current, decodeMessage(event.data)))
          } catch {
            setError('Received an unreadable telemetry message.')
          }
        }
        activeSocket.onerror = () => activeSocket.close()
        activeSocket.onclose = () => {
          if (socket !== activeSocket) return
          socket = null
          if (stopped) return
          setStream('polling')
          startPolling()
          const wait = Math.min(30_000, 1_000 * 2 ** Math.min(retryCount, 5))
          retryCount += 1
          retryTimer = window.setTimeout(connect, wait)
        }
      } catch {
        socket = null
        setStream('polling')
        startPolling()
        const wait = Math.min(30_000, 1_000 * 2 ** Math.min(retryCount, 5))
        retryCount += 1
        retryTimer = window.setTimeout(connect, wait)
      }
    }

    void poll()
    connect()
    return () => {
      stopped = true
      if (pollTimer !== undefined) window.clearInterval(pollTimer)
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      socket?.close()
    }
  }, [enabled])

  return { points, stream, error }
}
