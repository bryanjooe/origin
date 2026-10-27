import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { AutonomousAgentPanel } from './AutonomousAgentPanel'
import { api } from '../services/api'
import type { AgentJob, AgentReport, AgentStatus, AgentStep } from '../types/investigationAgent'

vi.mock('./charts/TimeSeriesChart',()=>({TimeSeriesChart:({data}:{data:unknown})=><pre data-testid="agent-chart">{JSON.stringify(data)}</pre>}))
const state={run_id:'run1',next_tick:10,simulation_status:'paused'}
const job:AgentJob={id:'agent-1',trigger:'manual',run_id:'run1',incident_id:'incident1',snapshot_tick:10,status:'completed',stage:'finished',created_at:'2026-10-27',finished_at:'2026-10-27',completed_experiments:1,report_available:true,stale:false,current_run_id:'run1',reason:null,error:null,events:[],progress_steps:[]}
const step:AgentStep={step:1,experiment_id:'test-1',intervention_id:'restore_controller_policy',selection_reason:'Controller residual exceeded its existing rule limit.',related_hypotheses:[{hypothesis_id:'controller_fault',explanation:'Possible malfunction'},{hypothesis_id:'controller_manipulation',explanation:'Possible manipulation'}],execution_status:'completed',start_tick:10,end_tick:30,comparable:true,exclusion_reason:null,intervention_outcome:'Relevant symptoms reduced',delivered_energy_difference_kwh:.768,physical_observations:{controller_policy_residual:{unit:'kW',control_mean_excess:2.3,experimental_mean_excess:0}},relevant_evidence:[{signal:'controller_policy_residual',tick:9,value:2.4,threshold:.1,unit:'kW',evidence_ids:[],provenance:['current_detection']}],limitations:['Prospective only.'],decision_afterward:{action:'stop',reason:'sufficient_intervention_evidence',explanation:'No further supported target is justified.',next_intervention:null,remaining_original_targets:[]},paired_telemetry:[{tick:10,control:{inverter_actual_kw:1,delivered_kw:.8},experimental:{inverter_actual_kw:2,delivered_kw:1.8}}]}
const report:AgentReport={investigation_id:'plan1',incident_id:'incident1',run_id:'run1',snapshot_tick:10,status:'completed',stopping_reason:'sufficient_intervention_evidence',stopping_explanation:'A relevant virtual abnormality was reduced.',executed_experiments:1,attempted_experiments:1,branch_ticks_charged:40,budget:{duration_ticks:20,max_experiments:3,max_branch_ticks:480},steps:[step],initial_plan:{context:{incident_observation_window:{run_id:'run1',start_tick:8,end_tick:9}}},initial_ai_assessment:{anomaly_status:'warning',phase1_prediction:'unknown',stage_b_origin:'Unknown',stage_b_nature:'Undetermined',original_model_records:[]},final_assessment:{most_useful_tested_intervention:null,intervention_effectiveness:'Intervention supported',source_evidence_assessment:'Inconclusive',historical_source:'Not established',malicious_intent:'Not established',additional_independent_evidence_required:true,reason:'Interventions do not prove historical origin.'},evidence_fusion:{limitations:['Historical source is not established.'],unresolved_hypotheses:step.related_hypotheses},recommended_next_actions:['Independently verify controller inputs.']}
let status:AgentStatus
let detail:AgentJob
beforeEach(()=>{
  detail={...job,report:structuredClone(report)}
  status={automatic_enabled:false,current_run_id:'run1',active:null,latest:null,recent:[],retention:20,lifecycle:'Process-local'}
  vi.spyOn(api,'getAgentStatus').mockImplementation(async()=>structuredClone(status))
  vi.spyOn(api,'getAgentInvestigation').mockImplementation(async()=>structuredClone(detail))
  vi.spyOn(api,'setAgentAutoMode').mockImplementation(async enabled=>{status.automatic_enabled=enabled;return structuredClone(status)})
  vi.spyOn(api,'startAgentInvestigation').mockImplementation(async()=>{status.latest={...job};status.recent=[{...job}];return {...job}})
})

it('renders actual backend automatic state and both control actions',async()=>{
  render(<AutonomousAgentPanel system={state} />)
  expect(await screen.findByText('Automatic Investigation Disabled')).toBeTruthy()
  expect(screen.getByRole('switch',{name:'Automatic Investigation'}).getAttribute('aria-checked')).toBe('false')
  expect(screen.getByRole('button',{name:'Start AI Investigation'})).toBeTruthy()
})

it('enables and disables automatic mode using confirmed backend responses',async()=>{
  render(<AutonomousAgentPanel system={state} />)
  const toggle=await screen.findByRole('switch',{name:'Automatic Investigation'})
  await waitFor(()=>expect((toggle as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(toggle)
  expect(await screen.findByText('Automatic Investigation Enabled')).toBeTruthy()
  expect(api.setAgentAutoMode).toHaveBeenLastCalledWith(true)
  fireEvent.click(toggle)
  expect(await screen.findByText('Automatic Investigation Disabled')).toBeTruthy()
  expect(api.setAgentAutoMode).toHaveBeenLastCalledWith(false)
})

it('does not invent an enabled state when the backend rejects a toggle',async()=>{
  vi.mocked(api.setAgentAutoMode).mockRejectedValue(new Error('Backend unavailable'))
  render(<AutonomousAgentPanel system={state} />)
  await screen.findByText('Automatic Investigation Disabled')
  fireEvent.click(screen.getByRole('switch',{name:'Automatic Investigation'}))
  expect((await screen.findByRole('alert')).textContent).toContain('Backend unavailable')
  expect(screen.queryByText('Automatic Investigation Enabled')).toBeNull()
})

it('starts the real API path with incident/run identity and renders reported values separately',async()=>{
  render(<AutonomousAgentPanel system={state} incidentId="incident1" />)
  await screen.findByText('Automatic Investigation Disabled')
  fireEvent.click(screen.getByRole('button',{name:'Start AI Investigation'}))
  expect(await screen.findByRole('region',{name:'Final Investigation Assessment'})).toBeTruthy()
  expect(api.startAgentInvestigation).toHaveBeenCalledWith('run1','incident1')
  expect(screen.getByText('+0.768 kWh')).toBeTruthy()
  expect(screen.getByText('Inconclusive')).toBeTruthy()
  expect(screen.getByRole('heading',{name:'Initial AI Assessment'})).toBeTruthy()
  expect(screen.getByRole('heading',{name:'Autonomous Experimental Findings'})).toBeTruthy()
  expect(screen.getByTestId('agent-chart').textContent).toContain('"original":1,"intervention":2')
  expect(screen.getByText('View Technical Investigation Report').closest('details')?.open).toBe(false)
})

it('prevents duplicate submissions while a start request is pending',async()=>{
  let resolve!:(value:AgentJob)=>void
  vi.mocked(api.startAgentInvestigation).mockImplementation(()=>new Promise(done=>{resolve=done}))
  render(<AutonomousAgentPanel system={state} />)
  await screen.findByText('Automatic Investigation Disabled')
  const button=screen.getByRole('button',{name:'Start AI Investigation'})
  fireEvent.click(button);fireEvent.click(button)
  expect(api.startAgentInvestigation).toHaveBeenCalledTimes(1)
  expect((button as HTMLButtonElement).disabled).toBe(true)
  await act(async()=>resolve(job))
})

it('renders genuine backend progress with no invented percentage',async()=>{
  status.active={...job,status:'investigating',stage:'running_shadowtwin',report_available:false,completed_experiments:0}
  status.recent=[status.active]
  detail={...status.active,report:null,progress_steps:[]}
  render(<AutonomousAgentPanel system={state} />)
  await screen.findAllByText('Running ShadowTwin')
  expect(await screen.findByText(/0 completed experiments/)).toBeTruthy()
  expect((screen.getByRole('button',{name:'Start AI Investigation'}) as HTMLButtonElement).disabled).toBe(true)
})

it('displays adaptive steps in their recorded order and switches measurement data',async()=>{
  detail.report!.steps.push({...structuredClone(step),step:2,experiment_id:'test-2',intervention_id:'use_redundant_solar',delivered_energy_difference_kwh:0,paired_telemetry:[{tick:10,control:{inverter_actual_kw:3},experimental:{inverter_actual_kw:4}}]})
  detail.report!.steps[0]!.decision_afterward={action:'continue',reason:'continue_with_supported_alternative',explanation:'Solar mismatch remains in the virtual result.',next_intervention:'use_redundant_solar',remaining_original_targets:['solar_measurement_residual']}
  status.latest=job;status.recent=[job]
  render(<AutonomousAgentPanel system={state} />)
  await screen.findByText('Next selected test: Solar measurement')
  const headings=screen.getAllByRole('heading',{level:4}).map(node=>node.textContent)
  expect(headings.indexOf('Step 1 — Controller')).toBeLessThan(headings.indexOf('Step 2 — Solar measurement'))
  fireEvent.change(screen.getByLabelText('Agent experiment'),{target:{value:'1'}})
  expect(screen.getByText('0 kWh')).toBeTruthy()
  expect(screen.getByTestId('agent-chart').textContent).toContain('"original":3,"intervention":4')
})

it('keeps negative energy and insufficient evidence honest',async()=>{
  detail.report!.steps[0]!.delivered_energy_difference_kwh=-.336
  detail.report!.final_assessment.intervention_effectiveness='Mixed evidence'
  detail.report!.stopping_explanation='No relevant comparison abnormality was measurable.'
  status.latest=job;status.recent=[job]
  render(<AutonomousAgentPanel system={state} />)
  expect(await screen.findByText('-0.336 kWh')).toBeTruthy()
  expect(screen.getByRole('heading',{name:'Mixed evidence'})).toBeTruthy()
})

it('shows an actual no-experiment reason and no fabricated chart',async()=>{
  detail.report!.steps=[];detail.report!.attempted_experiments=0;detail.report!.executed_experiments=0
  detail.report!.stopping_explanation='No dated component evidence supports a test.'
  detail.report!.final_assessment.intervention_effectiveness='Insufficient experimental evidence'
  status.latest=job;status.recent=[job]
  render(<AutonomousAgentPanel system={state} />)
  expect(await screen.findByText('No dated component evidence supports a test.')).toBeTruthy()
  expect(screen.queryByTestId('agent-chart')).toBeNull()
})

it('clears current-run selection on reset and allows explicit earlier-run history review',async()=>{
  status.latest=job;status.recent=[job]
  const view=render(<AutonomousAgentPanel system={state} />)
  await screen.findByText('+0.768 kWh')
  status.current_run_id='run2';status.latest=null;status.recent=[{...job,stale:true,current_run_id:'run2',status:'stale'}]
  view.rerender(<AutonomousAgentPanel system={{...state,run_id:'run2'}} />)
  await waitFor(()=>expect(screen.queryByText('+0.768 kWh')).toBeNull())
})

it('does not select an old-run start response that arrives after reset',async()=>{
  let resolve!:(value:AgentJob)=>void
  vi.mocked(api.startAgentInvestigation).mockImplementation(()=>new Promise(done=>{resolve=done}))
  const view=render(<AutonomousAgentPanel system={state} />)
  await screen.findByText('Automatic Investigation Disabled')
  fireEvent.click(screen.getByRole('button',{name:'Start AI Investigation'}))
  view.rerender(<AutonomousAgentPanel system={{...state,run_id:'run2'}} />)
  await act(async()=>resolve(job))
  expect(screen.queryByText('+0.768 kWh')).toBeNull()
})

it('handles status/API errors without enabling controls',async()=>{
  vi.mocked(api.getAgentStatus).mockRejectedValue(new Error('Sign in to use autonomous investigations'))
  render(<AutonomousAgentPanel system={state} />)
  expect((await screen.findByRole('alert')).textContent).toContain('Sign in')
  expect((screen.getByRole('switch',{name:'Automatic Investigation'}) as HTMLButtonElement).disabled).toBe(true)
})


it('preserves recorded Stage B outputs and labels an older assessment window',async()=>{
  detail.report!.initial_ai_assessment.stage_b_nature=null
  detail.report!.initial_ai_assessment.stage_b_origin=null
  detail.report!.initial_ai_assessment.original_model_records=[{model:'stage_b',scope:'historical_or_undated',original_fields:{available:true,status:'available',nature_verdict:'Undetermined',origin:'Unknown',window_end_tick:8},reported_candidates:[]}]
  status.latest=job;status.recent=[job]
  render(<AutonomousAgentPanel system={state} />)
  expect(await screen.findByText(/Stage B \(recorded incident window, available\): Undetermined · Unknown/)).toBeTruthy()
})
