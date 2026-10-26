import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveSimulationPage } from './LiveSimulationPage'
import { api } from '../services/api'
import { attackOptions } from '../types/attacks'
import type { SystemState } from '../types/domain'

const resource = vi.hoisted(() => ({
  data: { run_id: 'run-1', next_tick: 10, simulation_status: 'paused', components: [] } as SystemState,
  error: null as string | null, loading: false, reload: vi.fn(),
}))
vi.mock('../hooks/useApiResource', () => ({ useApiResource: () => resource }))
vi.mock('../hooks/useLiveTelemetry', () => ({ useLiveTelemetry: () => ({ points: [], stream: 'polling', error: null }) }))
vi.mock('../components/charts/TimeSeriesChart', () => ({ TimeSeriesChart: () => <div>Power chart</div> }))

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
const valid = { attack_type: 'sensor_spoof', target_component: 'solar_sensor', severity: 0.7, duration_ticks: 30, stealth_level: 'moderate' }
function fetchSuccess(start = 10) {
  const fetcher = vi.fn().mockResolvedValue(reply({ data: { scheduled: { ...valid, start_tick: start }, label: 'Simulated ground truth; not a model prediction' } }))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
function change(name: string, value: string) { fireEvent.change(screen.getByLabelText(name, { exact: true }), { target: { value } }) }
function inject() { fireEvent.click(screen.getByRole('button', { name: 'Inject Cyberattack' })) }
beforeEach(() => {
  resource.data = { run_id: 'run-1', next_tick: 10, simulation_status: 'paused', components: [] }
  resource.error = null
  resource.reload.mockClear()
})

describe('Live Simulation cyberattack controls', () => {
  it('adds the attack form while retaining existing controls, clock, and telemetry panels', () => {
    render(<LiveSimulationPage />)
    for (const name of ['Simulation controls', 'Simulation clock', 'Live power telemetry', 'Component status', 'Cyberattack Injection']) {
      expect(screen.getByRole('heading', { name })).toBeTruthy()
    }
    for (const name of ['Start', 'Pause', 'Resume', 'Reset', 'Inject fault', 'Inject Cyberattack']) expect(screen.getByRole('button', { name })).toBeTruthy()
    expect(screen.getByLabelText('Fault severity')).toBeTruthy()
    expect((screen.getByLabelText('Attack start') as HTMLSelectElement).value).toBe('next')
    expect(screen.queryByLabelText('Attack start tick')).toBeNull()
  })

  it.each([
    ['sensor_spoof', ['solar_sensor', 'battery_sensor', 'demand_sensor']],
    ['replay', ['communication']], ['communication_degradation', ['communication']],
    ['message_tampering', ['communication', 'controller', 'inverter']],
    ['controller_compromise', ['controller']], ['firmware_tampering', ['firmware']],
    ['actuator_abuse', ['inverter']],
    ['multi_stage', ['solar_sensor', 'battery_sensor', 'demand_sensor', 'communication', 'controller', 'firmware', 'inverter']],
  ])('offers backend-compatible targets for %s', (type, targets) => {
    render(<LiveSimulationPage />)
    change('Attack type', type as string)
    const select = screen.getByLabelText('Target component') as HTMLSelectElement
    expect(Array.from(select.options, (option) => option.value)).toEqual(targets)
    expect(targets).toContain(select.value)
    expect(Array.from((screen.getByLabelText('Attack type') as HTMLSelectElement).options, (option) => option.value)).toEqual(Object.keys(attackOptions))
  })

  it('replaces an incompatible target when attack type changes', () => {
    render(<LiveSimulationPage />)
    change('Target component', 'battery_sensor')
    change('Attack type', 'actuator_abuse')
    expect((screen.getByLabelText('Target component') as HTMLSelectElement).value).toBe('inverter')
    expect(within(screen.getByLabelText('Target component')).queryByRole('option', { name: 'Battery sensor' })).toBeNull()
  })

  it.each([
    ['Attack severity', '0'], ['Attack severity', '-0.1'], ['Attack severity', '1.1'], ['Attack severity', ''],
    ['Attack duration', '0'], ['Attack duration', '-1'], ['Attack duration', '1.5'], ['Attack duration', '10001'], ['Attack duration', ''],
  ])('rejects invalid %s: %s before a network request', (name, value) => {
    const fetcher = fetchSuccess()
    render(<LiveSimulationPage />)
    change(name, value)
    inject()
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('submits the exact next-tick request through the existing API and displays only the returned schedule', async () => {
    const fetcher = fetchSuccess(12)
    render(<LiveSimulationPage />)
    inject()
    expect(await screen.findByText(/Cyberattack scheduled successfully at tick 12 for 30 ticks/)).toBeTruthy()
    expect(fetcher).toHaveBeenCalledTimes(1)
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/simulation/inject-attack')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual(valid)
    expect(resource.reload).toHaveBeenCalledTimes(1)
    expect(resource.data.next_tick).toBe(10)
    expect(screen.queryByText(/attack detected/i)).toBeNull()
  })

  it('submits chosen type, target, severity, duration, stealth and future start tick', async () => {
    const fetcher = fetchSuccess(50)
    render(<LiveSimulationPage />)
    change('Attack type', 'message_tampering')
    change('Target component', 'controller')
    change('Attack severity', '0.8')
    change('Attack duration', '12')
    change('Stealth level', 'stealthy')
    change('Attack start', 'future')
    change('Attack start tick', '50')
    inject()
    await screen.findByText(/Cyberattack scheduled successfully/)
    expect(JSON.parse(fetcher.mock.calls[0]![1].body)).toEqual({ attack_type: 'message_tampering', target_component: 'controller', severity: 0.8, duration_ticks: 12, stealth_level: 'stealthy', start_tick: 50 })
  })

  it.each(['', '9', '10', '10.5', '9990', '10000'])('rejects invalid future tick or over-limit duration: %s', (tick) => {
    const fetcher = fetchSuccess()
    render(<LiveSimulationPage />)
    change('Attack start', 'future')
    change('Attack start tick', tick)
    inject()
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('omits a previously chosen future tick after switching back to next tick', async () => {
    const fetcher = fetchSuccess()
    render(<LiveSimulationPage />)
    change('Attack start', 'future'); change('Attack start tick', '50'); change('Attack start', 'next')
    inject()
    await screen.findByText(/Cyberattack scheduled successfully/)
    expect(JSON.parse(fetcher.mock.calls[0]![1].body)).not.toHaveProperty('start_tick')
  })

  it('blocks next-tick scheduling beyond the remaining horizon', () => {
    resource.data.next_tick = 9999
    const fetcher = fetchSuccess()
    render(<LiveSimulationPage />)
    inject()
    expect(screen.getByRole('alert').textContent).toContain('10000')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it.each([
    ['Overlapping attacks are not supported', []],
    ['Invalid request', [{ location: ['body', 'severity'], message: 'Input should be less than or equal to 1' }]],
  ])('shows real backend validation errors: %s', async (message, details) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ error: { message, details } }, 422)))
    render(<LiveSimulationPage />)
    inject()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(message)
    if (details.length) expect(alert.textContent).toContain('body.severity: Input should be less than or equal to 1')
    expect(screen.queryByText(/Cyberattack scheduled successfully/)).toBeNull()
    expect((screen.getByRole('button', { name: 'Inject Cyberattack' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('handles network failure and allows retry without false success', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue(reply({ data: { scheduled: { ...valid, start_tick: 10 }, label: 'Simulated ground truth' } }))
    vi.stubGlobal('fetch', fetcher)
    render(<LiveSimulationPage />)
    inject()
    expect((await screen.findByRole('alert')).textContent).toContain('Failed to fetch')
    expect(screen.queryByText(/Cyberattack scheduled successfully/)).toBeNull()
    inject()
    expect(await screen.findByText(/Cyberattack scheduled successfully/)).toBeTruthy()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('locks duplicate submissions and existing mutations until the request completes', async () => {
    let resolve!: (response: Response) => void
    const fetcher = vi.fn().mockImplementation(() => new Promise<Response>((done) => { resolve = done }))
    vi.stubGlobal('fetch', fetcher)
    render(<LiveSimulationPage />)
    inject(); inject()
    expect(fetcher).toHaveBeenCalledTimes(1)
    for (const name of ['Inject Cyberattack', 'Start', 'Resume', 'Reset']) expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => resolve(reply({ data: { scheduled: { ...valid, start_tick: 10 }, label: 'Simulated ground truth' } })))
    expect((screen.getByRole('button', { name: 'Resume' }) as HTMLButtonElement).disabled).toBe(false)
    expect(await screen.findByText(/Cyberattack scheduled successfully/)).toBeTruthy()
  })

  it('clears stale success on a new run and leaves the form usable', async () => {
    fetchSuccess()
    const view = render(<LiveSimulationPage />)
    inject(); await screen.findByText(/Cyberattack scheduled successfully/)
    resource.data = { ...resource.data, run_id: 'run-2', next_tick: 0 }
    view.rerender(<LiveSimulationPage />)
    expect(screen.queryByText(/Cyberattack scheduled successfully/)).toBeNull()
    expect((screen.getByRole('button', { name: 'Inject Cyberattack' }) as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByLabelText('Attack start') as HTMLSelectElement).value).toBe('next')
  })

  it('disables scheduling when current system state is unavailable', () => {
    resource.error = 'Backend disconnected'
    render(<LiveSimulationPage />)
    expect((screen.getByRole('button', { name: 'Inject Cyberattack' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it.each([
    ['Start', 'startSimulation'], ['Pause', 'pauseSimulation'], ['Resume', 'resumeSimulation'],
    ['Reset', 'resetSimulation'], ['Inject fault', 'injectFault'],
  ] as const)('preserves the existing %s handler', async (button, method) => {
    resource.data.simulation_status = ['Pause', 'Inject fault'].includes(button) ? 'running' : 'paused'
    const spy = vi.spyOn(api, method).mockResolvedValue({})
    render(<LiveSimulationPage />)
    if (button === 'Inject fault') change('SCENARIO', 'sensor')
    fireEvent.click(screen.getByRole('button', { name: button }))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    expect(resource.reload).toHaveBeenCalledTimes(1)
  })
})
