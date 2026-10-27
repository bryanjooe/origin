"""Exercise the unchanged active model bundle through the real FastAPI lifespan.

Uses a separate in-memory database, preserving the user's live run and history.
Labels below select verification scenarios only; they never enter inference.
"""
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
from app.api.config import ServerSettings
from app.main import create_app


def main():
    artifact=Path('outputs/step5/candidates/regular/selected.joblib').resolve()
    settings=ServerSettings(database_path=':memory:',security_model=artifact,security_results_dir=artifact.parent)
    cases=[('normal',None,{}),
        ('controller_compromise','attack',{'attack_type':'controller_compromise','target_component':'controller'}),
        ('sensor_spoof','attack',{'attack_type':'sensor_spoof','target_component':'solar_sensor'}),
        ('replay','attack',{'attack_type':'replay','target_component':'communication'}),
        ('message_tampering','attack',{'attack_type':'message_tampering','target_component':'communication'}),
        ('communication_degradation','attack',{'attack_type':'communication_degradation','target_component':'communication'}),
        ('inverter_fault','fault',{'kind':'inverter','mode':'derate'}),
        ('sensor_fault','fault',{'kind':'sensor','mode':'bias'}),
        ('ambiguous_inverter_shutdown','fault',{'kind':'inverter','mode':'shutdown'})]
    results=[]
    with TestClient(create_app(settings)) as c:
        assert c.post('/api/auth/register',json={'name':'Isolated reliability check','email':'accuracy@example.test','password':'isolated-test-only'}).status_code==201
        def call(method,path,body=None):
            r=c.request(method,path,json=body)
            assert r.status_code in (200,202),(path,r.text)
            return r.json()['data']
        for name,kind,body in cases:
            call('POST','/api/agent/auto-mode',{'enabled':False})
            call('POST','/api/simulation/scenario',{'seed':42,'config':{'start_hour':17,'communication_delay_ticks':3}})
            call('POST','/api/agent/auto-mode',{'enabled':True})
            if kind:
                payload={**body,'severity':1 if name=='ambiguous_inverter_shutdown' else .8,'start_tick':10,'duration_ticks':80}
                if kind=='attack':payload['stealth_level']='moderate'
                call('POST','/api/simulation/inject-'+kind,payload)
            call('POST','/api/simulation/step',{'ticks':110})
            deadline=time.monotonic()+30
            status=call('GET','/api/agent/status')
            while status['active'] and time.monotonic()<deadline:
                time.sleep(.02);status=call('GET','/api/agent/status')
            assert not status['active'],'Bounded investigation did not finish'
            live=call('GET','/api/system/state');run_id=live['run_id']
            jobs=[j for j in status['recent'] if j['run_id']==run_id]
            reports=[call('GET','/api/agent/investigations/'+j['id']) for j in jobs if j['report_available']]
            assert all(j['report']['branch_ticks_charged']<=480 and j['report']['attempted_experiments']<=3 for j in reports)
            assert len({j['incident_id'] for j in reports})==len(reports),'Automatic duplicate'
            for _ in range(3):call('GET','/api/agent/status')
            assert len(call('GET','/api/agent/status')['recent'])==len(status['recent'])
            assert live['next_tick']==110 and live['running'] is False
            items=call('GET','/api/incidents?run_id='+run_id)['items']
            details=[call('GET','/api/incidents/'+i['id']) for i in items]
            runtime=c.app.state.runtime
            stored=runtime.store.telemetry(run_id,-1,1000)
            active=[r for r in stored if not kind or 10<=r['telemetry']['tick']<90]
            result={'case':name,'evaluated_ticks':len(active),
                'ml_alert_ticks':sum(r['anomaly']['ml_status']!='normal' for r in active),
                'combined_alert_ticks':sum(r['anomaly']['combined_status']!='normal' for r in active),
                'incidents':len(items),'automatic_report_count':len(reports),'automatic_skip_count':len(jobs)-len(reports),
                'investigation_budget_respected':True,'duplicate_prevention_verified':True,'live_next_tick_after_agent':live['next_tick'],
                'security_assessments':[d['security_attribution'] for d in details],
                'last_source':live['source'],'model_fingerprints':runtime.models.fingerprints}
            results.append(result)
            print(name,'ML/combined',result['ml_alert_ticks'],result['combined_alert_ticks'],'incidents',len(items),'agent reports',len(reports),flush=True)
    output=Path('outputs/accuracy-optimization/runtime_verification.json')
    output.write_text(json.dumps({'active_models_changed':False,'database':'isolated in-memory; live user database untouched','results':results},indent=2),encoding='utf-8')


if __name__=='__main__':main()
