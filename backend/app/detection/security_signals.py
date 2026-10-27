"""Experimental causal security sidecar; importing it changes no live detector.

No simulation object, schedule, label or source prediction enters extraction.
The original Isolation Forest score and ML label are preserved by fusion.
"""
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import math

import numpy as np
from sklearn.ensemble import IsolationForest

from .features import FeatureExtractor, Observation


SIGNAL_VERSION = 1
SIGNALS = ('auth_invalid_rate', 'sequence_anomaly_rate', 'solar_redundancy_gap', 'soc_redundancy_gap')
FLOORS = {'auth_invalid_rate':.25, 'sequence_anomaly_rate':.125,
          'solar_redundancy_gap':.01, 'soc_redundancy_gap':.001}


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


class SecuritySignalExtractor:
    """Latest eight ticks, minimum four observations per domain, no backfill.

    Authentication counts distinct observed controller packets, not repeated
    reuse of a stale invalid tag. Missing/unknown tags are unavailable, not bad.
    Sequence flags come from the existing sender/receiver observable logs.
    Redundancy uses measured primary and independent redundant readings only.
    """
    def __init__(self, config):
        self.config=config
        self.window=deque(maxlen=8)
        self.previous_tick=None

    def update(self,row):
        tick=row.get('tick')
        if type(tick) is not int or tick<0 or self.previous_tick is not None and tick!=self.previous_tick+1:
            raise ValueError('Security observations require consecutive run ticks')
        security=row.get('security_telemetry')
        security=security if isinstance(security,Mapping) else {}
        packet=row.get('controller_inputs')
        packet=packet if isinstance(packet,Mapping) else {}
        identity=packet.get('sequence_number',security.get('message_sequence_number'))
        # Without a genuine numeric packet identity, authentication is unavailable.
        identity=identity if type(identity) is int and identity>=0 else None
        tag=security.get('auth_tag_validity')
        auth=(identity,tag=='invalid') if identity is not None and tag in ('valid','invalid') else None
        flags=(security.get('duplicate_sequence'),security.get('out_of_order_sequence'))
        sequence=float(any(flags)) if all(type(v) is bool for v in flags) else None
        def gap(primary,redundant,scale):
            a,b=row.get(primary),row.get(redundant,security.get(redundant))
            return abs(a-b)/scale if finite(a) and finite(b) else None
        sample={'auth':auth,'sequence_anomaly_rate':sequence,
            'solar_redundancy_gap':gap('measured_solar_kw','redundant_solar_kw',self.config.solar_capacity_kw),
            'soc_redundancy_gap':gap('measured_soc_pct','redundant_soc_pct',100)}
        window=[*self.window,sample][-8:]
        unique={s['auth'][0]:float(s['auth'][1]) for s in window if s['auth'] is not None}
        domains={'auth_invalid_rate':list(unique.values()),
            **{name:[s[name] for s in window if s[name] is not None] for name in SIGNALS[1:]}}
        result={'tick':tick,'values':{name:float(np.mean(v)) if v else 0.0 for name,v in domains.items()},
                'counts':{name:len(v) for name,v in domains.items()}}
        self.window.append(sample);self.previous_tick=tick
        return result

    def transform(self,rows):return [self.update(row) for row in rows]


class SecuritySidecar:
    """One finite comparison: empirical envelopes or a normal-only small IF."""
    def __init__(self,method='envelope',quantile=.999):
        if method not in ('envelope','isolation_forest'):raise ValueError('Unsupported sidecar')
        self.method,self.quantile=method,quantile
        self.limits={};self.forest=None;self.columns=[];self.metadata={}

    def fit(self,training,calibration):
        def matrix(samples):
            return np.asarray([[s['values'][name] for name in SIGNALS] for s in samples
                if all(s['counts'][name]>=4 for name in SIGNALS)])
        train,cal=matrix(training),matrix(calibration)
        if len(train)<256 or len(cal)<128:raise ValueError('Insufficient complete normal windows')
        variation=np.std(train,axis=0)
        self.columns=[i for i,v in enumerate(variation) if v>1e-12]
        self.metadata={'signal_version':SIGNAL_VERSION,'window_ticks':8,'minimum_observations':4,
            'training_rows':len(train),'calibration_rows':len(cal),
            'training_std':dict(zip(SIGNALS,variation.tolist())),
            'constant_features_excluded_from_if':[n for i,n in enumerate(SIGNALS) if i not in self.columns]}
        if self.method=='envelope':
            self.limits={name:max(FLOORS[name],float(np.quantile(cal[:,i],self.quantile))) for i,name in enumerate(SIGNALS)}
        else:
            if not self.columns:raise ValueError('No variable normal signals')
            self.forest=IsolationForest(n_estimators=100,max_samples=256,random_state=41821,n_jobs=1).fit(train[:,self.columns])
            self.limits={'novelty':float(np.quantile(-self.forest.score_samples(cal[:,self.columns]),self.quantile))}
        return self

    def infer(self,samples):
        if not self.limits:raise RuntimeError('Sidecar is not fitted')
        results=[]
        scores=None
        if self.forest is not None:
            x=np.asarray([[s['values'][SIGNALS[i]] for i in self.columns] for s in samples])
            scores=-self.forest.score_samples(x) if len(x) else []
        for i,s in enumerate(samples):
            if self.forest is not None:
                available=all(s['counts'][name]>=4 for name in SIGNALS)
                findings=[{'signal':'security_window_novelty','value':float(scores[i]),
                    'threshold':self.limits['novelty'],'unit':'normal-trained IF score','method':'security_isolation_forest'}] if available and scores[i]>self.limits['novelty'] else []
            else:
                findings=[{'signal':name,'value':s['values'][name],'threshold':self.limits[name],
                    'unit':'fraction' if 'rate' in name else 'normalized independent-sensor gap',
                    'method':'normal_calibrated_security_envelope'} for name in SIGNALS
                    if s['counts'][name]>=4 and s['values'][name]>self.limits[name]]
            results.append(findings)
        return results

    def fuse(self,baseline,samples):
        if len(baseline)!=len(samples):raise ValueError('Baseline and sidecar ticks must align')
        output=deepcopy(baseline)
        for result,s,findings in zip(output,samples,self.infer(samples)):
            if result['tick']!=s['tick']:raise ValueError('Baseline and sidecar ticks must align')
            result['security_signal_findings']=findings
            result['security_signal_method']=self.method
            if findings:
                result['combined_status']=result['combined_status'] if result['combined_status']!='normal' else 'warning'
                # Findings are labeled with their actual method, never ML attribution
                # to the original Isolation Forest or a claimed attack/source.
                result['residual_checks']=[*result['residual_checks'],*findings]
                if self.method=='envelope':result['rule_status']='warning'
        return output


def persistent_fusion(baseline,samples,sidecar=None):
    """Validation refinement: three observations, fixed before final evaluation.

    Preserve existing residual rules and critical ML alerts immediately. Original
    ML scores/labels remain unchanged. Combined unsupported warnings and newly
    observed security bounds require three consecutive ticks, matching the
    existing incident confirmation length. No model thresholds are altered.
    """
    if len(baseline)!=len(samples):raise ValueError('Baseline and sidecar ticks must align')
    output=deepcopy(baseline);warning_run=0;signal_runs={};previous=None
    findings=sidecar.infer(samples) if sidecar is not None else [[] for _ in samples]
    for result,s,found in zip(output,samples,findings):
        if result['tick']!=s['tick'] or previous is not None and result['tick']!=previous+1:
            raise ValueError('Fusion requires consecutive aligned ticks from one run')
        previous=result['tick']
        warning_run=warning_run+1 if result['ml_status']!='normal' else 0
        current={f['signal'] for f in found}
        signal_runs={name:(signal_runs.get(name,0)+1 if name in current else 0) for name in set(signal_runs)|current}
        confirmed=[f for f in found if signal_runs[f['signal']]>=3]
        combined=(result['ml_status'] if result['ml_status']=='critical' or warning_run>=3 else
                  'warning' if result['residual_checks'] or confirmed else 'normal')
        result.update(combined_status=combined,security_signal_findings=confirmed,
            security_signal_method='persistent_normal_envelope' if sidecar is not None else 'persistence_only_control',
            combined_policy='Existing residual/critical alerts immediate; unsupported ML and security findings require 3 consecutive ticks')
        result['residual_checks']=[*result['residual_checks'],*confirmed]
        if confirmed:result['rule_status']='warning'
    return output


@dataclass
class SecurityObservation(Observation):
    security_signal_sample: dict


class SidecarFeatureExtractor:
    """Optional live-compatible composition; the legacy extractor is unmodified."""
    def __init__(self,config):
        self.base=FeatureExtractor(config);self.security=SecuritySignalExtractor(config)

    def update(self,row):
        base=self.base.update(row)
        signal=self.security.update(row)
        return SecurityObservation(base.tick,base.elapsed_seconds,base.features,base.residual_checks,signal)

    def transform(self,rows):return [self.update(row) for row in rows]
