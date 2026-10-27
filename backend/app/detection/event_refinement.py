"""Final experimental policies; no production loader imports this module.

Inputs are original observable detector outputs and causal signal samples only.
No incident truth, event schedule or source label is accepted by this interface.
"""
from collections import deque
from copy import deepcopy


def onset_fusion(baseline,samples,sidecar,*,security_quorum=3):
    """Prompt weak-warning onsets with a fixed three-tick emission interval.

    Existing physical residual/critical alerts are immediate. Weak ML evidence
    emits immediately when the last weak-only pulse is >=3 ticks old; it does
    not have to remain abnormal for three ticks. Security evidence uses either
    three consecutive findings or two of the latest three, with a current real
    finding required. These are the only two declared validation candidates.

    New security findings are separate detector evidence, not additions to the
    physical residual schema consumed by the already calibrated Stage B gate.
    Its score, original residuals and raw telemetry remain available unchanged;
    new incidents without an admissible Stage B window remain pending/unknown.
    """
    if security_quorum not in (2,3):raise ValueError('Only the two declared policies are supported')
    if len(baseline)!=len(samples):raise ValueError('Detector and signal ticks must align')
    results=deepcopy(baseline);history=deque(maxlen=3);last_pulse=None;previous=None
    for row,sample,findings in zip(results,samples,sidecar.infer(samples)):
        tick=row['tick']
        if tick!=sample['tick'] or previous is not None and tick!=previous+1:
            raise ValueError('Consecutive aligned observations from one run are required')
        previous=tick
        history.append({f['signal'] for f in findings})
        confirmed=[f for f in findings if sum(f['signal'] in h for h in history)>=security_quorum]
        physical=bool(row['residual_checks']);critical=row['ml_status']=='critical'
        pulse=(row['ml_status']=='warning' and not physical and
               (last_pulse is None or tick-last_pulse>=3))
        if pulse:last_pulse=tick
        row['combined_status']='critical' if critical else 'warning' if physical or pulse or confirmed else 'normal'
        row['security_signal_findings']=confirmed
        row['security_signal_method']=f'onset_pulse_security_{security_quorum}_of_3'
        row['combined_policy']='Original residual/critical alerts immediate; weak ML onset pulse at most every 3 ticks; separately confirmed security observations'
        row['weak_ml_onset_pulse']=pulse
        row['security_stage_b_scope']='Detector observations only; original calibrated Stage B score/residual gate unchanged'
    return results
