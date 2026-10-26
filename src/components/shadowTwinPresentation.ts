import type { ShadowComparison } from '../types/shadowtwin'

export const interventionNames: Record<string, string> = {
  use_redundant_solar: 'Solar measurement', restore_controller_policy: 'Controller', flush_communication: 'Communication',
}
export const signalNames: Record<string, string> = {
  solar_measurement_residual: 'Solar measurement mismatch', soc_step_residual: 'Battery charge-step mismatch',
  soc_energy_estimate_residual: 'Battery energy mismatch', inverter_output_residual: 'Inverter output mismatch',
  controller_policy_residual: 'Controller command mismatch', stale_telemetry: 'Stale communication data',
  configuration_integrity: 'Configuration mismatch', packet_local_solar_disagreement: 'Received solar mismatch',
}
export function outcomeLabel(value: string) {
  return ({ 'Relevant symptoms reduced': 'Improved', 'Mixed effects': 'Mixed results',
    'No relevant symptom improvement': 'No meaningful change', 'Worsened delivered energy': 'Worsened energy delivery',
    'Relevant residual reduction with worsened delivered energy': 'Residual improved; energy delivery worsened',
    'Energy gain only': 'Energy gain only — no relevant symptom improvement', 'Not evaluated': 'Not evaluated' } as Record<string, string>)[value] ?? value
}

// Presentation of backend decisions only: never calculate new ranks or thresholds.
export function shadowConclusion(result: ShadowComparison) {
  const items = result.hypotheses
  if (items.length && items.every(item => item.experiment_status === 'unsupported'))
    return { title: 'Unsupported Experiment', detail: 'The selected interventions could not be applied. Review the backend limitations and choose another supported test.', kind: 'warning' as const }
  if (items.length && items.every(item => ['failed', 'invalid'].includes(item.experiment_status)))
    return { title: 'Experiment Failed', detail: 'The virtual experiments did not complete. Review the reported error before retrying.', kind: 'critical' as const }
  if (result.inconclusive_reasons.some(reason => reason.startsWith('No above-threshold control abnormality')))
    return { title: 'No Relevant Abnormality Detected', detail: 'No relevant abnormality was measurable in this experiment. The selected incident may no longer be active. Run a new test while the abnormal condition is active.', kind: 'warning' as const }
  const front = result.intervention_ranking?.find(group => group.position === 1)
  const best = front?.hypothesis_ids.length === 1 ? items.find(item => item.hypothesis_id === front.hypothesis_ids[0]) : undefined
  if (result.status === 'Ranked prospective evidence' && best)
    return { title: `${interventionNames[best.intervention] ?? 'Tested'} Intervention Performed Best`, detail: 'The backend found stronger relative support for this tested intervention. Its measured effects are shown below; historical origin and malicious intent remain unproven.', kind: 'normal' as const }
  if (front && front.hypothesis_ids.length > 1 && front.relationship === 'equivalent')
    return { title: 'Multiple Equally Supported Outcomes', detail: 'The backend found equivalent top outcomes. These experiments cannot distinguish the competing explanations; the conclusion remains Inconclusive.', kind: 'warning' as const }
  return { title: 'No Clear Cause Identified', detail: front?.relationship === 'trade_off'
    ? 'The best outcomes have conflicting trade-offs. The backend does not select a single cause; the conclusion remains Inconclusive.'
    : 'The available experiments do not identify a reliable cause. Review the backend reasons below; intervention effectiveness is separate from source evidence.', kind: 'warning' as const }
}
