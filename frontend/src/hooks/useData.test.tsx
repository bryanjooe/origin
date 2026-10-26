import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mergePoints, useAction, useLiveData } from './useData'
import type { TelemetryPoint } from '../types'

const point = (tick: number) => ({ telemetry: { tick } }) as TelemetryPoint
describe('live data lifecycle', () => {
  it('merges cursor pages in order and replaces duplicate ticks', () => {
    expect(mergePoints([point(1), point(2)], [point(2), point(3)], false).map(p => p.telemetry.tick)).toEqual([1, 2, 3])
  })
  it('drops the previous scenario history on a new run', () => {
    expect(mergePoints([point(140)], [point(0), point(1)], true).map(p => p.telemetry.tick)).toEqual([0, 1])
  })
  it('bounds chart history without changing the backend cursor ordering', () => {
    const merged = mergePoints([], Array.from({ length: 400 }, (_, i) => point(i)), false)
    expect(merged).toHaveLength(240); expect(merged[0].telemetry.tick).toBe(160)
  })
  it('prevents overlapping mutations and refreshes after completion', async () => {
    let finish!: (value: Response) => void
    const fetcher = vi.fn().mockReturnValue(new Promise<Response>(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', fetcher)
    const refresh = vi.fn()
    const { result } = renderHook(() => useAction(refresh))
    let pending!: Promise<void>
    act(() => { pending = result.current.act('/simulation/start'); void result.current.act('/simulation/start') })
    expect(fetcher).toHaveBeenCalledTimes(1)
    await act(async () => { finish(new Response('{"data":{}}')); await pending })
    expect(refresh).toHaveBeenCalledOnce(); expect(result.current.busy).toBe(false)
  })
  it('keeps backend errors visible and refreshes on a conflict', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"error":{"message":"Fault overlaps"}}', { status: 422 })))
    const refresh = vi.fn()
    const { result } = renderHook(() => useAction(refresh))
    await act(async () => { await result.current.act('/simulation/inject-fault') })
    expect(result.current.error).toBe('Fault overlaps'); expect(result.current.message).toBeNull()
  })
  it('does not fill an offline dashboard with zero-valued synthetic state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Backend offline')))
    const { result } = renderHook(() => useLiveData())
    await waitFor(() => expect(result.current.error).toBe('Backend offline'))
    expect(result.current.data).toBeNull()
  })
})
