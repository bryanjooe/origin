import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../services/api'
import type { ShadowComparison } from '../types/shadowtwin'
import { ShadowTwinPanel } from './ShadowTwinPanel'

vi.mock('./charts/TimeSeriesChart', () => ({TimeSeriesChart: ({data,unit}: {data:unknown;unit:string}) => <pre data-testid="comparison-chart">{JSON.stringify({data,unit})}</pre>}))
const system = {run_id:'run1',next_tick:10}
function result(): ShadowComparison {
  return {comparison_id:'comparison1',run_id:'run1',current_run_id:'run1',run_changed:false,snapshot_tick:10,
    start_tick:10,end_tick:30,incident_id:null,incident_run_id:null,historical_incident:false,
    status:'Inconclusive',historical_source:'Not established',hypothesis_ranking:[],intervention_ranking:[],
    tied_or_tradeoff_groups:[['solar_fault','controller_manipulation']],inconclusive_reasons:['Recorded observations do not distinguish the candidates.'],limitations:['Prospective only.'],
    hypotheses:[{hypothesis_id:'solar_fault',suspected_component:'solar_sensor',proposed_mechanism:'possible sensor error',intervention:'use_redundant_solar',
      experiment_status:'completed',ranking_position:1,intervention_rank:1,evidence_assessment:'Partial evidence support',intervention_outcome:'Mixed effects',
      delivered_energy_difference_kwh:-0.25,explanation:'Actual backend explanation: residual improved but another measurement worsened.',warnings:['Redundant sensor health is not guaranteed.'],
      physical_observations:{solar_measurement_residual:{unit:'noise stddev',control_mean_excess:6,experimental_mean_excess:0}},
      experiment:{start_tick:10,end_tick:30,execution_tick:10,intervention_status:'sustained_for_experiment',sustained:true,
        control_telemetry:[{tick:10,inverter_actual_kw:1,delivered_kw:0.8,battery_soc_pct:60}],
        experimental_telemetry:[{tick:10,inverter_actual_kw:2,delivered_kw:1.8,battery_soc_pct:59}],warnings:[],limitations:['No historical source proof.']}}]}
}
function select() {
  fireEvent.click(screen.getByRole('checkbox',{name:/Solar sensor malfunction/}))
  fireEvent.click(screen.getByRole('checkbox',{name:/Controller command manipulation/}))
}
function run() { fireEvent.click(screen.getByRole('button',{name:'Run ShadowTwin Analysis'})) }
afterEach(() => {vi.restoreAllMocks()})

it('renders six explicit hypotheses, manual context and historical-origin warning', () => {
  render(<ShadowTwinPanel system={system} />)
  expect(screen.getByRole('heading',{name:'ShadowTwin — Virtual Investigation'})).toBeTruthy()
  expect(screen.getAllByRole('checkbox')).toHaveLength(6)
  expect(screen.getAllByRole('checkbox').every(node => !(node as HTMLInputElement).checked)).toBe(true)
  expect(screen.getByText(/Manual prospective experiment/)).toBeTruthy()
  expect(screen.getByText(/do not independently prove/)).toBeTruthy()
})

it('rejects insufficient selection without submitting', async () => {
  const spy=vi.spyOn(api,'compareShadowTwin')
  render(<ShadowTwinPanel system={system} />); run()
  expect((await screen.findByRole('alert')).textContent).toContain('at least two')
  expect(spy).not.toHaveBeenCalled()
})

it.each(['0','-1','1.5','121'])('rejects invalid duration or budget %s', async duration => {
  const spy=vi.spyOn(api,'compareShadowTwin')
  render(<ShadowTwinPanel system={system} />); select()
  fireEvent.change(screen.getByLabelText('ShadowTwin duration'),{target:{value:duration}});run()
  expect(await screen.findByRole('alert')).toBeTruthy();expect(spy).not.toHaveBeenCalled()
})

it('sends exact endpoint identifiers and incident/run context then displays actual backend values', async () => {
  const response=result()
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({data:response}),{status:200}))
  vi.stubGlobal('fetch',fetcher)
  render(<ShadowTwinPanel incidentId="incident1" system={system} />);select();run()
  expect(await screen.findByText(response.hypotheses[0]!.explanation)).toBeTruthy()
  const [url,init]=fetcher.mock.calls[0]!
  expect(url).toBe('/api/shadowtwin/compare')
  const request=JSON.parse(init.body)
  expect(request.expected_run_id).toBe('run1');expect(request.incident_id).toBe('incident1')
  expect(request.duration_ticks).toBe(20)
  expect(request.hypotheses.map((h:{intervention:string})=>h.intervention)).toEqual(['use_redundant_solar','restore_controller_policy'])
  expect(request.hypotheses[0]).not.toHaveProperty('name')
  expect(screen.getByText('-0.25 kWh')).toBeTruthy()
  expect(screen.getByText('Inconclusive — Available evidence does not distinguish these hypotheses.')).toBeTruthy()
  expect(screen.getByText('Partial evidence support')).toBeTruthy()
  expect(screen.getByText('Mixed effects')).toBeTruthy()
  expect(screen.getByTestId('comparison-chart').textContent).toContain('"control":1,"experimental":2')
  fireEvent.change(screen.getByLabelText('ShadowTwin measurement'),{target:{value:'battery_soc_pct'}})
  expect(screen.getByTestId('comparison-chart').textContent).toContain('"control":60,"experimental":59')
})

it('locks repeated submissions until completion and does not show success early', async () => {
  let resolve!: (value: ShadowComparison)=>void
  const spy=vi.spyOn(api,'compareShadowTwin').mockImplementation(()=>new Promise(done=>{resolve=done}))
  render(<ShadowTwinPanel system={system} />);select();run();run()
  expect(spy).toHaveBeenCalledTimes(1)
  expect((screen.getByRole('button',{name:'Run ShadowTwin Analysis'}) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByText(/Captured run/)).toBeNull()
  await act(async()=>resolve(result()))
  expect(screen.getByText(/Captured run/)).toBeTruthy()
})

it('shows backend errors and permits retry', async () => {
  const spy=vi.spyOn(api,'compareShadowTwin').mockRejectedValueOnce(new Error('Snapshot unavailable')).mockResolvedValue(result())
  render(<ShadowTwinPanel system={system} />);select();run()
  expect((await screen.findByRole('alert')).textContent).toContain('Snapshot unavailable')
  expect(screen.queryByText(/Captured run/)).toBeNull()
  run();await screen.findByText(/Captured run/);expect(spy).toHaveBeenCalledTimes(2)
})

it('clears completed results when incident context changes', async () => {
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(result())
  const view=render(<ShadowTwinPanel system={system} incidentId="old" />);select();run()
  await screen.findByText(/Captured run/)
  view.rerender(<ShadowTwinPanel system={system} incidentId="new" />)
  expect(screen.queryByText(/Captured run/)).toBeNull()
})

it('discards an old response after a simulation reset', async () => {
  let resolve!: (value:ShadowComparison)=>void
  vi.spyOn(api,'compareShadowTwin').mockImplementation(()=>new Promise(done=>{resolve=done}))
  const view=render(<ShadowTwinPanel system={system} />);select();run()
  view.rerender(<ShadowTwinPanel system={{run_id:'run2',next_tick:0}} />)
  await act(async()=>resolve(result()))
  expect(screen.queryByText(/Captured run/)).toBeNull()
  await waitFor(()=>expect((screen.getByRole('button',{name:'Run ShadowTwin Analysis'}) as HTMLButtonElement).disabled).toBe(false))
})

it.each(['unsupported','failed'])('displays %s without invented chart data or energy', async status => {
  const response=result();const item=response.hypotheses[0]!
  item.experiment_status=status;item.experiment=null;item.delivered_energy_difference_kwh=null
  item.ranking_position=null;item.intervention_rank=null
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run()
  await screen.findByText(/Experiment:/)
  expect(screen.getByText('No matching comparison telemetry')).toBeTruthy()
  expect(screen.getByText('Unavailable')).toBeTruthy()
})

it('reports missing response data instead of crashing or displaying success', async () => {
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue({run_id:'run1',snapshot_tick:10,status:'Inconclusive',hypotheses:[{}]} as ShadowComparison)
  render(<ShadowTwinPanel system={system} />);select();run()
  expect((await screen.findByRole('alert')).textContent).toContain('missing or incompatible')
  expect(screen.queryByText(/Captured run/)).toBeNull()
})

it('marks historical incident references and results from a reset run explicitly', async () => {
  const response={...result(),historical_incident:true,run_changed:true,current_run_id:'run2'}
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} incidentId="historical" />);select();run()
  expect(await screen.findByText(/Historical incident reference only/)).toBeTruthy()
  expect((await screen.findByRole('alert')).textContent).toContain('belong only to captured run run1')
})
