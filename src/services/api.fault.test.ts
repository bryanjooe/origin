import { describe, expect, it, vi } from 'vitest'
import { api } from './api'

const payload = { scenario: 'sensor', severity: 0.7, start_tick: 30, seed: 42 }
const reply = (data: unknown) => new Response(JSON.stringify({ data }), { status: 200 })

describe('equipment fault scheduling against the current server clock', () => {
  it.each([30, 180])('uses the server-selected next tick for a stale/equal tick at %s', async (next_tick) => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply({ next_tick }))
      .mockResolvedValueOnce(reply({ scheduled: { start_tick: next_tick + 3 } }))
    vi.stubGlobal('fetch', fetcher)
    await api.injectFault(payload)
    expect(fetcher.mock.calls[0]![0]).toBe('/api/system/state')
    const [url, request] = fetcher.mock.calls[1]!
    expect(url).toBe('/api/simulation/inject-fault')
    expect(JSON.parse(request.body)).toEqual({ kind: 'sensor', mode: 'bias', severity: 0.7, duration_ticks: 120 })
  })

  it('preserves an explicitly chosen future tick', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply({ next_tick: 180 }))
      .mockResolvedValueOnce(reply({ scheduled: { start_tick: 250 } }))
    vi.stubGlobal('fetch', fetcher)
    await api.injectFault({ ...payload, start_tick: 250 })
    expect(JSON.parse(fetcher.mock.calls[1]![1].body)).toEqual({ kind: 'sensor', mode: 'bias', severity: 0.7, start_tick: 250, duration_ticks: 120 })
  })

  it('keeps the existing duration cap within the remaining horizon', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply({ next_tick: 9990 }))
      .mockResolvedValueOnce(reply({ scheduled: { start_tick: 9990 } }))
    vi.stubGlobal('fetch', fetcher)
    await api.injectFault(payload)
    expect(JSON.parse(fetcher.mock.calls[1]![1].body).duration_ticks).toBe(10)
  })

  it('does not post when the clock is unavailable', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetcher)
    await expect(api.injectFault(payload)).rejects.toThrow('Failed to fetch')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('preserves backend overlap rejection without rescheduling or retrying', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply({ next_tick: 180 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: 'Fault overlaps a scheduled fault in the uncorrected comparison run' } }), { status: 422 }))
    vi.stubGlobal('fetch', fetcher)
    await expect(api.injectFault(payload)).rejects.toThrow('uncorrected comparison run')
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})
