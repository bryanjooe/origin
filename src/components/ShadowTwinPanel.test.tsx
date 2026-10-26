import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  expect(screen.getByRole('heading', {name:'No Clear Cause Identified'})).toBeTruthy()
  expect(screen.getByText('Inconclusive')).toBeTruthy()
  expect(screen.getByText('Partial evidence support')).toBeTruthy()
  expect(screen.getByText('Mixed results')).toBeTruthy()
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


it('groups the workflow into three categories while preserving all six API hypotheses', async () => {
  const response=result()
  const spy=vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />)
  for (const name of ['Select Investigation','Choose What to Test','Run Investigation'])
    expect(screen.getByRole('heading',{name:new RegExp(name)})).toBeTruthy()
  for (const category of ['Solar Measurement','Controller Behavior','Communication'])
    fireEvent.click(screen.getByRole('button',{name:`Test ${category}`}))
  run();await screen.findByText(/Captured run/)
  const request=spy.mock.calls[0]![0]
  expect(request.hypotheses).toHaveLength(6)
  expect(request.hypotheses.map(item=>item.intervention)).toEqual(['use_redundant_solar','use_redundant_solar','restore_controller_policy','restore_controller_policy','flush_communication','flush_communication'])
  expect(request.duration_ticks).toBe(20)
  expect(screen.getAllByText(/Equivalent results cannot distinguish malfunction/)).toHaveLength(3)
})

it('keeps technical settings and evidence collapsed by default', async () => {
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(result())
  render(<ShadowTwinPanel system={system} />)
  expect(screen.getByText('Advanced Settings').closest('details')?.open).toBe(false)
  select();run();await screen.findByText(/Captured run/)
  const disclosure=screen.getByText('View Technical Evidence').closest('details')!
  expect(disclosure.open).toBe(false)
  fireEvent.click(screen.getByText('View Technical Evidence'))
  expect(disclosure.open).toBe(true)
  expect(screen.getByText(result().hypotheses[0]!.explanation)).toBeTruthy()
})

it('shows the backend strongest controller intervention without source certainty', async () => {
  const response=result(), item=response.hypotheses[0]!
  Object.assign(item,{hypothesis_id:'controller_fault',intervention:'restore_controller_policy',suspected_component:'controller',
    physical_observations:{controller_policy_residual:{unit:'kW',control_mean_excess:2.3,experimental_mean_excess:0}},
    evidence_assessment:'Stronger relative evidence support',intervention_outcome:'Relevant symptoms reduced',delivered_energy_difference_kwh:0.768})
  response.status='Ranked prospective evidence'
  response.intervention_ranking=[{position:1,hypothesis_ids:['controller_fault'],relationship:'distinguishable'}]
  response.tied_or_tradeoff_groups=[];response.inconclusive_reasons=[]
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run()
  expect(await screen.findByRole('heading',{name:'Controller Intervention Performed Best'})).toBeTruthy()
  expect(screen.getByText('+0.768 kWh')).toBeTruthy()
  expect(screen.getByText(/historical origin and malicious intent remain unproven/)).toBeTruthy()
  expect(screen.getByText('Improved')).toBeTruthy()
  expect(within(screen.getByRole('region',{name:'What Changed in the Virtual Experiment?'})).getByText('2.3', {exact:false})).toBeTruthy()
})

it('preserves an equivalent top group and an actual zero energy difference', async () => {
  const response=result()
  response.intervention_ranking=[{position:1,hypothesis_ids:['solar_fault','controller_manipulation'],relationship:'equivalent'}]
  response.hypotheses[0]!.delivered_energy_difference_kwh=0
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run()
  expect(await screen.findByRole('heading',{name:'Multiple Equally Supported Outcomes'})).toBeTruthy()
  expect(screen.getByText('0 kWh')).toBeTruthy()
  expect(screen.queryByText(/Intervention Performed Best/)).toBeNull()
})

it('explains the backend no-abnormality reason with cautious next-step guidance', async () => {
  const response=result()
  response.inconclusive_reasons=['No above-threshold control abnormality was measurable using the existing residual rules.']
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run()
  expect(await screen.findByRole('heading',{name:'No Relevant Abnormality Detected'})).toBeTruthy()
  expect(screen.getByText(/selected incident may no longer be active/)).toBeTruthy()
  expect(screen.getByText('Inconclusive')).toBeTruthy()
})

it('separates same-run earlier observations from the current snapshot before submission', () => {
  render(<ShadowTwinPanel incidentId="old" system={{...system,next_tick:881,simulation_status:'paused'}}
    incident={{id:'old',title:'Earlier incident',runId:'run1',startTick:57,endTick:82}} />)
  expect(screen.getByText('Historical Incident — Current-State Test')).toBeTruthy()
  expect(screen.getByText('Ticks 57–82')).toBeTruthy()
  expect(screen.getByText('881')).toBeTruthy()
  expect(screen.getByText(/not replaying the incident from its original start/)).toBeTruthy()
})

it('updates comparison data when the viewed hypothesis changes and keeps earlier IDs technical', async () => {
  const response=result(), original=response.hypotheses[0]!
  original.recorded_evidence_ids=['t57:solar_measurement_residual']
  response.hypotheses.push({...original,hypothesis_id:'controller_manipulation',recorded_evidence_ids:[],
    experiment:{...original.experiment!,experimental_telemetry:[{tick:10,inverter_actual_kw:9}]}})
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run();await screen.findByText(/Captured run/)
  expect(screen.getByTestId('comparison-chart').textContent).toContain('"experimental":2')
  fireEvent.change(screen.getByLabelText('ShadowTwin result hypothesis'),{target:{value:'controller_manipulation'}})
  expect(screen.getByTestId('comparison-chart').textContent).toContain('"experimental":9')
  expect(screen.getByText(/Earlier incident evidence IDs:/).closest('details')?.open).toBe(false)
})


it('does not turn a Pareto trade-off into an equivalent tie or a winner', async () => {
  const response=result()
  response.intervention_ranking=[{position:1,hypothesis_ids:['solar_fault','controller_manipulation'],relationship:'trade_off'}]
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run()
  expect(await screen.findByRole('heading',{name:'No Clear Cause Identified'})).toBeTruthy()
  expect(screen.getByText(/conflicting trade-offs/)).toBeTruthy()
  expect(screen.queryByRole('heading',{name:'Multiple Equally Supported Outcomes'})).toBeNull()
})

it.each([['unsupported','Unsupported Experiment'],['failed','Experiment Failed']])('shows the actual %s conclusion', async (status,title) => {
  const response=result()
  Object.assign(response.hypotheses[0]!,{experiment_status:status,experiment:null,delivered_energy_difference_kwh:null})
  vi.spyOn(api,'compareShadowTwin').mockResolvedValue(response)
  render(<ShadowTwinPanel system={system} />);select();run()
  expect(await screen.findByRole('heading',{name:title})).toBeTruthy()
  expect(screen.queryByTestId('comparison-chart')).toBeNull()
})


it('maps the existing incident observation period without exposing hidden labels', async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({data:{
    id:'old:incident1',run_id:'old',first_observed_tick:57,last_alert_tick:82,
    diagnosis:{source:'unknown'},ground_truth:{attack_target:'controller'},timeline:[],
  }}))))
  const incident=await api.getIncident('old:incident1')
  expect(incident.run_id).toBe('old')
  expect(incident.first_observed_tick).toBe(57)
  expect(incident.last_alert_tick).toBe(82)
  expect(incident).not.toHaveProperty('ground_truth')
})
