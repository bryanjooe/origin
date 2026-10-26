import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { InvestigationPage, SecurityAttributionCard } from './InvestigationPage'
import { api } from '../services/api'
import type { SecurityAttribution } from '../types/domain'

const resource = vi.hoisted(() => ({
  assessment: undefined as SecurityAttribution | undefined,
  hook: vi.fn(), reload: vi.fn(),
}))
vi.mock('../hooks/useApiResource', () => ({ useApiResource: (...args: unknown[]) => {
  resource.hook(...args)
  const key = String(args[0])
  const data = key === 'investigation-incidents' ? [{ id: 'run:incident-1', source: 'sensor', severity: 'warning', status: 'open', confidence: 0.81 }]
    : key.startsWith('incident-detail') ? { id: 'run:incident-1', source: 'sensor', confidence: 0.81, summary: 'Existing source hypothesis', security_attribution: resource.assessment }
    : { nodes: [], edges: [] }
  return { data, loading: false, error: null, reload: resource.reload }
} }))
vi.mock('../components/system/DependencyGraph', () => ({ DependencyGraph: () => <div>Dependency graph</div> }))

const available: SecurityAttribution = {
  available: true, model_available: true, status: 'available', nature_verdict: 'Cyber attack', nature_confidence: 0.73,
  origin: 'Communication', origin_confidence: 0.62, confidence_kind: 'uncalibrated_random_forest_probability',
  inference_tick: 31, window_start_tick: 12, window_end_tick: 31, window_ticks: 20, window_complete: true,
  origin_candidates: [{ layer: 'Communication', confidence: 0.62 }, { layer: 'Sensor', confidence: 0.24 }],
  evidence: { statement: 'Observed indicators are not proof of intent.', uncertainty: 'Multiple candidates remain plausible.',
    points_toward_attack: [{ name: 'Invalid authentication tags', value: '4 of 20', unit: 'messages' }],
    ambiguous: [{ name: 'Mean message age', value: 120, unit: 'seconds' }] },
}

beforeEach(() => { resource.assessment = undefined; resource.hook.mockClear(); resource.reload.mockClear() })

describe('AI Security Assessment', () => {
  it('renders actual categories, scores, candidates and window details separately from source diagnosis', () => {
    resource.assessment = available
    render(<InvestigationPage />)
    expect(screen.getByRole('heading', { name: 'AI Security Assessment' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Model assessment' })).toBeTruthy()
    expect(screen.getByText('Existing source hypothesis')).toBeTruthy()
    expect(screen.getByText('Cyber attack')).toBeTruthy()
    expect(screen.getByText('Uncalibrated model score: 73%')).toBeTruthy()
    expect(screen.getByText('Uncalibrated model score: 62%')).toBeTruthy()
    expect(screen.getByText('Inference at tick 31')).toBeTruthy()
    expect(screen.getByText('Analysis available')).toBeTruthy()
    expect(resource.hook.mock.calls.some(([key, , refresh]) => String(key).startsWith('incident-detail') && refresh === 3000)).toBe(true)
  })

  it('shows only the supporting observations returned by the backend', () => {
    render(<SecurityAttributionCard attribution={available} loading={false} />)
    expect(screen.getByText('Invalid authentication tags')).toBeTruthy()
    expect(screen.getByText('4 of 20 messages')).toBeTruthy()
    expect(screen.getByText('120 seconds')).toBeTruthy()
    expect(screen.getByText('Observed indicators are not proof of intent.')).toBeTruthy()
    expect(screen.getByText('Multiple candidates remain plausible.')).toBeTruthy()
    expect(screen.getByText(/Uncalibrated model scores are not calibrated probabilities/)).toBeTruthy()
  })

  it('preserves model abstention and does not invent an origin score', () => {
    render(<SecurityAttributionCard attribution={{ ...available, nature_verdict: 'Undetermined', origin: 'Unknown', origin_confidence: null }} loading={false} />)
    expect(screen.getAllByText('Undetermined').length).toBe(2)
    expect(screen.getByText('Unknown')).toBeTruthy()
    expect(screen.getByText('Uncalibrated model score: Unknown')).toBeTruthy()
    expect(screen.queryByText('Cyber attack')).toBeNull()
  })

  it.each([
    ['pending', 'Pending telemetry'], ['insufficient_evidence', 'Insufficient evidence'], ['unavailable', 'Model unavailable'],
  ] as const)('displays %s without prediction or score', (status, title) => {
    render(<SecurityAttributionCard attribution={{ available: false, status, nature_verdict: 'Undetermined', reason: 'Backend reason: insufficient observations or missing artifact.' }} loading={false} />)
    expect(screen.getByText(title)).toBeTruthy()
    expect(screen.getByText('Backend reason: insufficient observations or missing artifact.')).toBeTruthy()
    expect(screen.queryByText(/model score:/i)).toBeNull()
    expect(screen.queryByText('Cyber attack')).toBeNull()
  })

  it('handles an omitted assessment gracefully', () => {
    render(<SecurityAttributionCard loading={false} />)
    expect(screen.getByText('Model unavailable')).toBeTruthy()
    expect(screen.getByText(/backend did not return a Stage B prediction/)).toBeTruthy()
  })

  it('renders the existing loading state', () => {
    render(<SecurityAttributionCard loading />)
    expect(screen.getByText('Loading security assessment')).toBeTruthy()
  })

  it('keeps saved calibration metadata accurate without claiming guaranteed reliability', () => {
    render(<SecurityAttributionCard attribution={{ ...available, confidence_kind: 'sigmoid_calibrated_probability' }} loading={false} />)
    expect(screen.getByText('Model score: 73%')).toBeTruthy()
    expect(screen.queryByText('Uncalibrated model score: 73%')).toBeNull()
    expect(screen.getByText(/saved artifact reports sigmoid calibration/)).toBeTruthy()
    expect(screen.getByText(/does not guarantee reliability on live incidents/)).toBeTruthy()
  })

  it('keeps graph, evidence, timeline and the original correction action available', async () => {
    resource.assessment = available
    const correction = vi.spyOn(api, 'applyCorrection').mockResolvedValue({ message: 'Simulated correction applied.' })
    render(<InvestigationPage />)
    for (const name of ['Propagation graph', 'Evidence and checks', 'Symptom timeline', 'Affected downstream components']) expect(screen.getByRole('heading', { name })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Apply simulated corrective action' }))
    expect(await screen.findByText('Simulated correction applied.')).toBeTruthy()
    expect(correction).toHaveBeenCalledWith('run:incident-1')
  })

  it('maps backend security fields intact while retaining the Phase 1 diagnosis', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { id: 'run:incident-1', diagnosis: { source: 'sensor', confidence: 0.81 }, security_attribution: available } })))
    vi.stubGlobal('fetch', fetcher)
    const incident = await api.getIncident('run:incident-1')
    expect(incident.source).toBe('sensor')
    expect(incident.security_attribution).toEqual(available)
    render(<SecurityAttributionCard attribution={incident.security_attribution} loading={false} />)
    const panel = screen.getByRole('heading', { name: 'AI Security Assessment' }).closest('section')!
    expect(within(panel).getByText('Cyber attack')).toBeTruthy()
  })
})
