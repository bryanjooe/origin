"""Real API/agent checks in isolated storage; never mutate the user's live run."""
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
from app.api.config import ServerSettings
from app.main import create_app
from app.detection.security_signals import SecuritySignalExtractor


def main():
    output=Path('outputs/security-detector-study-v1/runtime_verification.json')
    path=Path('outputs/step5/candidates/regular/selected.joblib').resolve()
    settings=ServerSettings(database_path=':memory:',security_model=path,security_results_dir=path.parent)
    cases=[('normal',None,{}),('controller','attack',{'attack_type':'controller_compromise','target_component':'controller'}),
        ('sensor_spoof','attack',{'attack_type':'sensor_spoof','target_component':'solar_sensor'}),
        ('replay','attack',{'attack_type':'replay','target_component':'communication'}),
        ('message_tampering','attack',{'attack_type':'message_tampering','target_component':'communication'}),
        ('communication_degradation','attack',{'attack_type':'communication_degradation','target_component':'communication'}),
        ('sensor_fault','fault',{'kind':'sensor','mode':'bias'}),('inverter_fault','fault',{'kind':'inverter','mode':'derate'})]
    results=[]
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/auth/register',json={'name':'Security signal check','email':'signals@example.test','password':'isolated-test-only'}).status_code==201
        def call(method,url,body=None):
            r=client.request(method,url,json=body);assert r.status_code in (200,202),(url,r.text)
            return r.json()['data']
        for name,kind,body in cases:
            call('POST','/api/simulation/scenario',{'seed':42,'config':{'start_hour':17,'communication_delay_ticks':3}})
            call('POST','/api/agent/auto-mode',{'enabled':True})
            if kind:
                payload={**body,'severity':.8,'start_tick':10,'duration_ticks':80}
                if kind=='attack':payload['stealth_level']='moderate'
                call('POST','/api/simulation/inject-'+kind,payload)
            call('POST','/api/simulation/step',{'ticks':110})
            status=call('GET','/api/agent/status');deadline=time.monotonic()+30
            while status['active'] and time.monotonic()<deadline:
                time.sleep(.02);status=call('GET','/api/agent/status')
            assert not status['active']
            state=call('GET','/api/system/state');runtime=client.app.state.runtime
            assert state['next_tick']==110 and not state['running']
            records=runtime.store.telemetry(state['run_id'],-1,1000)
            rows=[r['telemetry'] for r in records]
            batch=SecuritySignalExtractor(runtime.sim.config).transform(rows)
            streaming=SecuritySignalExtractor(runtime.sim.config)
            assert batch==[streaming.update(r) for r in rows]
            assert all('security_signal_findings' not in r['anomaly'] for r in records),'Experimental policy was accidentally activated'
            jobs=[j for j in status['recent'] if j['run_id']==state['run_id'] and j['report_available']]
            assert len({j['incident_id'] for j in jobs})==len(jobs)
            for j in jobs:
                report=call('GET','/api/agent/investigations/'+j['id'])['report']
                assert report['attempted_experiments']<=3 and report['branch_ticks_charged']<=480
            for _ in range(3):call('GET','/api/agent/status')
            assert len(call('GET','/api/agent/status')['recent'])==len(status['recent'])
            items=call('GET','/api/incidents?run_id='+state['run_id'])['items']
            assessments=[call('GET','/api/incidents/'+i['id'])['security_attribution'] for i in items]
            result={'case':name,'recorded_ticks':len(rows),'observable_signal_batch_streaming_equal':True,
                'current_run_incidents':len(items),'automatic_reports':len(jobs),'budget_and_duplicate_checks_passed':True,
                'live_tick_after_investigation':state['next_tick'],'model_fingerprints':runtime.models.fingerprints,
                'security_assessments':assessments}
            results.append(result)
            print(name,'incidents',len(items),'automatic reports',len(jobs),'signal parity OK',flush=True)
    output.write_text(json.dumps({'active_models_changed':False,'database':'isolated in-memory','experimental_policy_activated':False,
        'scope':'Unchanged production application compatibility plus causal extraction from actual persisted telemetry; rejected candidates are not live.',
        'results':results},indent=2),encoding='utf-8')


if __name__=='__main__':main()
