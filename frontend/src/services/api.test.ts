import { describe, expect, it, vi } from 'vitest'
import { ApiError, exportUrl, get, post } from './api'

describe('FastAPI integration contract', () => {
  it('unwraps actual response envelopes and passes cancellation', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { run_id: 'run', next_tick: 4 } })))
    vi.stubGlobal('fetch', fetcher)
    const signal = new AbortController().signal
    expect(await get('/system/state', signal)).toEqual({ run_id: 'run', next_tick: 4 })
    expect(fetcher).toHaveBeenCalledWith('/api/system/state', expect.objectContaining({ signal }))
  })
  it('sends a fault schedule as a JSON POST', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"data":{"scheduled":true}}'))
    vi.stubGlobal('fetch', fetcher)
    const fault = { kind: 'sensor', mode: 'bias', severity: 0.8, duration_ticks: 30 }
    await post('/simulation/inject-fault', fault)
    expect(fetcher).toHaveBeenCalledWith('/api/simulation/inject-fault', expect.objectContaining({ method: 'POST', body: JSON.stringify(fault) }))
  })
  it('surfaces backend conflicts without converting them to success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"error":{"message":"Pause before resetting"}}', { status: 409 })))
    await expect(post('/simulation/reset')).rejects.toThrow('Pause before resetting')
  })
  it('shows field-level validation details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: 'Invalid request', details: [{ location: ['body', 'ticks'], message: 'Must be positive' }] } }), { status: 422 })))
    await expect(post('/simulation/step', { ticks: 0 })).rejects.toThrow('body.ticks: Must be positive')
  })
  it('reports a missing data envelope rather than fabricating state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}')))
    await expect(get('/system/state')).rejects.toBeInstanceOf(ApiError)
  })
  it('does not treat an HTML proxy error as valid data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Error</html>', { status: 502 })))
    await expect(get('/system/state')).rejects.toThrow('unreadable response')
  })
  it('encodes export identifiers without dropping the selected run', () => {
    expect(exportUrl('incidents', 'csv', 'run:1')).toContain('run_id=run%3A1')
  })
})
