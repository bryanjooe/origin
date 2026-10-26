import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { InvestigationPage } from './InvestigationPage'
import { api } from '../services/api'
import type { IncidentDetail, TopologyNode } from '../types/domain'

const resource = vi.hoisted(() => ({ detail: {} as IncidentDetail, hook: vi.fn() }))
vi.mock('../hooks/useApiResource', () => ({ useApiResource: (...args: unknown[]) => {
  resource.hook(...args)
  return { data: String(args[0]) === 'investigation-incidents' ? [{ id: 'run:1', source: 'sensor', severity: 'warning', status: 'open' }] : resource.detail,
    loading: false, error: null, reload: vi.fn() }
} }))
vi.mock('../components/system/DependencyGraph', () => ({ DependencyGraph: ({nodes, onNodeSelect, highlightedNodes = []}: {
  nodes: TopologyNode[]; onNodeSelect: (node: TopologyNode) => void; highlightedNodes?: string[]
}) => <div><div data-testid="event-focus">{highlightedNodes.join(',')}</div>{nodes.map(node => <button key={node.id} onClick={()=>onNodeSelect(node)}>Select {node.label}</button>)}</div> }))

beforeEach(() => {
  resource.hook.mockClear()
  resource.detail = {
    id: 'run:1', summary: 'Existing source diagnosis', security_attribution: { available: true, status: 'available', nature_verdict: 'Undetermined', origin: 'Unknown' },
    graph: { nodes: [{ id: 'inverter', label: 'Inverter', observed_symptom: true, potentially_affected: true,
      direct_evidence: [{ id: 't25:inverter_output_residual', tick: 25, description: 'Recorded inverter residual', value: 4.2, threshold: 0.58, unit: 'kW' }],
      events: [{ tick: 25, event: 'symptom_observed', evidence_id: 't25:inverter_output_residual' }], telemetry: { tick:25, inverter_actual_kw:0 }, downstream_dependencies: ['delivered'] },
      { id:'controller', label:'Controller', downstream_dependencies:['inverter','delivered'] }, {id:'communication',label:'Communication'}], edges:[],
      security_origin_message: 'Security origin has not been established.', security_paths:[] },
    timeline: [{ tick:25, event:'symptom_observed', nodes:['inverter'], signal:'inverter_output_residual', evidence_id:'t25:inverter_output_residual' },
      {tick:12,event:'incident_confirmed',nodes:[]},{tick:18,event:'symptom_observed',signal:'packet_local_solar_disagreement',nodes:['communication','controller']}],
  }
})

it('keeps both diagnoses and observations visible without inventing an Unknown attack origin', () => {
  render(<InvestigationPage />)
  expect(screen.getByRole('heading',{name:'AI Security Assessment'})).toBeTruthy()
  expect(screen.getByRole('heading',{name:'Model assessment'})).toBeTruthy()
  expect(screen.getByText('Existing source diagnosis')).toBeTruthy()
  expect(screen.getByText('Security origin has not been established.')).toBeTruthy()
  expect(screen.getByText(/Amber border\/path: Phase 1 hypothesis/)).toBeTruthy()
  expect(resource.hook.mock.calls.some(([key])=>String(key).startsWith('incident-graph'))).toBe(false)
})
it('selects a component and shows its actual evidence IDs, values, ticks, and dependencies', () => {
  render(<InvestigationPage />)
  fireEvent.click(screen.getByRole('button',{name:'Select Inverter'}))
  const panel=screen.getByRole('complementary',{name:'Inverter component details'})
  expect(within(panel).getByText('Recorded inverter residual')).toBeTruthy()
  expect(within(panel).getByText(/Evidence t25:inverter_output_residual · Tick 25 · 4.2 kW/)).toBeTruthy()
  expect(within(panel).getByText(/Observed abnormality/)).toBeTruthy()
  expect(within(panel).getByText(/Structural reachability does not establish compromise/)).toBeTruthy()
})
it('switches components and handles missing direct evidence without creating measurements', () => {
  render(<InvestigationPage />)
  fireEvent.click(screen.getByRole('button',{name:'Select Inverter'}))
  fireEvent.click(screen.getByRole('button',{name:'Select Controller'}))
  const panel=screen.getByRole('complementary',{name:'Controller component details'})
  expect(within(panel).getByText('No direct anomaly evidence available for this component.')).toBeTruthy()
  expect(within(panel).queryByText('Recorded inverter residual')).toBeNull()
  fireEvent.click(within(panel).getByRole('button',{name:'Close'}))
  expect(screen.queryByRole('complementary')).toBeNull()
})
it('orders recorded events and uses an event to select its component and evidence', () => {
  render(<InvestigationPage />)
  const timeline=screen.getByRole('heading',{name:'Symptom timeline'}).closest('section')!
  const buttons=within(timeline).getAllByRole('button')
  expect(buttons[0]!.textContent).toBe('incident_confirmed')
  expect(buttons[1]!.textContent).toContain('packet local solar disagreement')
  expect(buttons[2]!.textContent).toContain('inverter output residual')
  fireEvent.click(buttons[2]!)
  expect(screen.getByTestId('event-focus').textContent).toBe('inverter')
  expect(screen.getByRole('complementary',{name:'Inverter component details'})).toBeTruthy()
  expect(within(timeline).getByText('Recorded inverter residual')).toBeTruthy()
})
it('highlights all components in ambiguous events without choosing an arbitrary origin', () => {
  render(<InvestigationPage />)
  fireEvent.click(screen.getByRole('button',{name:/symptom_observed · packet local solar disagreement/}))
  expect(screen.getByTestId('event-focus').textContent).toBe('communication,controller')
  expect(screen.queryByRole('complementary')).toBeNull()
  expect(screen.getByText(/No associated anomaly evidence was recorded for this event/)).toBeTruthy()
})
it('handles a recorded event without node or evidence associations honestly', () => {
  render(<InvestigationPage />)
  fireEvent.click(screen.getByRole('button',{name:'incident_confirmed'}))
  expect(screen.getByTestId('event-focus').textContent).toBe('')
  expect(screen.getByText(/Selected event: incident_confirmed · No associated component recorded/)).toBeTruthy()
})
it('refreshes the selected component evidence without clearing selection', () => {
  const view=render(<InvestigationPage />)
  fireEvent.click(screen.getByRole('button',{name:'Select Inverter'}))
  const node=resource.detail.graph!.nodes[0]!
  resource.detail={...resource.detail,graph:{...resource.detail.graph!,nodes:[{...node,direct_evidence:[{id:'t26:residual',tick:26,description:'Updated recorded residual',value:5.1}]},...resource.detail.graph!.nodes.slice(1)]}}
  view.rerender(<InvestigationPage />)
  expect(within(screen.getByRole('complementary',{name:'Inverter component details'})).getByText('Updated recorded residual')).toBeTruthy()
})
it('preserves enriched node metadata and timeline associations in the API mapper',async()=>{
  const graph={...resource.detail.graph!,nodes:[{...resource.detail.graph!.nodes[0],telemetry:[{tick:24,inverter_actual_kw:1},{tick:25,inverter_actual_kw:0}]}]}
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({data:{id:'run:1',diagnosis:{source:'sensor'},graph,timeline:resource.detail.timeline}}))))
  const incident=await api.getIncident('run:1')
  expect(incident.graph!.nodes[0]!.telemetry).toEqual({tick:25,inverter_actual_kw:0})
  expect(incident.graph!.nodes[0]!.direct_evidence![0]!.id).toBe('t25:inverter_output_residual')
  expect(incident.timeline!.map(event=>event.tick)).toEqual([12,18,25])
  expect(incident.timeline![2]!.nodes).toEqual(['inverter'])
  expect(incident.timeline![2]!.evidence_id).toBe('t25:inverter_output_residual')
})
