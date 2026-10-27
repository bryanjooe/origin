"""Authenticated API, backend-driven triggers, lifecycle and shared-worker safety."""
import asyncio
from copy import deepcopy
import json
import pickle
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest
from app.api.config import ServerSettings
from app.main import create_app
from app.investigation_agent import manager as agent_module


@pytest.fixture
def client(workspace_tmp_path):
    settings=ServerSettings(database_path=workspace_tmp_path/'agent.sqlite3',source_model=None,security_model=None)
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/auth/register',json={'name':'Agent integration test','email':'agent@example.test','password':'local-test-password'}).status_code==201
        yield client


def data(response):
    assert response.status_code in (200,202),response.text
    return response.json()['data']


def configure(client,kind='controller'):
    data(client.post('/api/simulation/scenario',json={'config':{'start_hour':17,'communication_delay_ticks':3}}))
    if kind=='controller':
        data(client.post('/api/simulation/inject-attack',json={'attack_type':'controller_compromise','target_component':'controller','severity':.8,'duration_ticks':100}))
    else:
        data(client.post('/api/simulation/inject-fault',json={'kind':'sensor','mode':'bias','severity':.8,'duration_ticks':100}))


def wait_job(client,ident):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        job=data(client.get('/api/agent/investigations/'+ident))
        if job['status']!='investigating':return job
        time.sleep(.01)
    raise AssertionError('Agent job did not finish')


def automatic_job(client):
    state=data(client.get('/api/agent/status'))
    job=state['active'] or state['latest']
    assert job,state
    return wait_job(client,job['id'])


def test_default_off_and_validated_authenticated_controls(client):
    assert data(client.get('/api/agent/status'))['automatic_enabled'] is False
    assert client.post('/api/agent/auto-mode',json={'enabled':'yes'}).status_code==422
    assert client.post('/api/agent/auto-mode',json={'enabled':True,'ground_truth':'controller'}).status_code==422
    assert data(client.post('/api/agent/auto-mode',json={'enabled':True}))['automatic_enabled'] is True
    assert data(client.post('/api/agent/auto-mode',json={'enabled':False}))['automatic_enabled'] is False
    client.post('/api/auth/logout')
    for path in ('/status','/investigations','/investigations/missing'):
        assert client.get('/api/agent'+path).status_code==401
    assert client.post('/api/agent/auto-mode',json={'enabled':True}).status_code==401


def test_untrusted_browser_origin_is_rejected(client):
    assert client.post('/api/agent/auto-mode',json={'enabled':True},headers={'Origin':'https://untrusted.example'}).status_code==403
    assert client.post('/api/agent/auto-mode',json={'enabled':False},headers={'Origin':'http://testserver'}).status_code==200


@pytest.mark.parametrize('kind,mechanism',[('controller','restore_controller_policy'),('sensor','use_redundant_solar')])
def test_new_incident_triggers_without_a_browser_or_manual_hypotheses(client,kind,mechanism):
    configure(client,kind)
    data(client.post('/api/agent/auto-mode',json={'enabled':True}))
    data(client.post('/api/simulation/step',json={'ticks':10}))
    job=automatic_job(client)
    assert job['trigger']=='automatic' and job['report']
    assert job['report']['steps'][0]['intervention_id']==mechanism
    assert job['report']['final_assessment']['source_evidence_assessment']=='Inconclusive'
    assert job['report']['branch_ticks_charged']<=480
    assert job['snapshot_tick']<=10
    encoded=json.dumps(job)
    assert all(key not in encoded for key in ('ground_truth','target_component','_schedule','training_labels'))


def test_old_incident_and_persistent_anomaly_do_not_loop(client):
    configure(client)
    data(client.post('/api/simulation/step',json={'ticks':10}))
    assert data(client.get('/api/incidents'))['total']>0
    data(client.post('/api/agent/auto-mode',json={'enabled':True}))
    data(client.post('/api/simulation/step',json={'ticks':5}))
    assert data(client.get('/api/agent/status'))['recent']==[]


def test_successful_automatic_incident_is_not_reinvestigated_by_updates_or_reads(client):
    configure(client);data(client.post('/api/agent/auto-mode',json={'enabled':True}))
    data(client.post('/api/simulation/step',json={'ticks':10}));job=automatic_job(client)
    for _ in range(3): data(client.get('/api/agent/status'));data(client.get('/api/agent/investigations/'+job['id']))
    data(client.post('/api/simulation/step',json={'ticks':10}))
    recent=data(client.get('/api/agent/status'))['recent']
    assert len([item for item in recent if item['incident_id']==job['incident_id'] and item['status']!='skipped'])==1


def test_auto_disabled_does_not_start_and_manual_uses_the_same_engine(client):
    configure(client);data(client.post('/api/simulation/step',json={'ticks':10}))
    assert not data(client.get('/api/agent/status'))['recent']
    state=data(client.get('/api/system/state'))
    started=data(client.post('/api/agent/investigate',json={'expected_run_id':state['run_id']}))
    result=wait_job(client,started['id'])
    assert result['trigger']=='manual'
    assert result['report']['steps'][0]['intervention_id']=='restore_controller_policy'
    repeated=data(client.post('/api/agent/investigate',json={'expected_run_id':state['run_id']}))
    assert repeated['id']==started['id']


def test_manual_insufficient_evidence_retains_real_reason_and_no_measurements(client):
    state=data(client.get('/api/system/state'))
    job=data(client.post('/api/agent/investigate',json={'expected_run_id':state['run_id']}))
    done=wait_job(client,job['id'])
    assert done['status']=='insufficient_evidence'
    assert done['report']['attempted_experiments']==0
    assert done['report']['steps']==[]
    assert data(client.get('/api/agent/investigations'))
    assert client.get('/api/agent/investigations/missing').status_code==404


@pytest.mark.parametrize('change',[{'max_experiments':4},{'duration_ticks':0},{'duration_ticks':True},{'duration_ticks':241},{'max_branch_ticks':481},{'hidden_target':'controller'}])
def test_request_budgets_and_unknown_fields_are_rejected(client,change):
    state=data(client.get('/api/system/state'))
    assert client.post('/api/agent/investigate',json={'expected_run_id':state['run_id'],**change}).status_code==422
    assert data(client.get('/api/agent/status'))['recent']==[]


def test_stale_manual_request_and_unknown_incident(client):
    assert client.post('/api/agent/investigate',json={'expected_run_id':'old'}).status_code==409
    state=data(client.get('/api/system/state'))
    assert client.post('/api/agent/investigate',json={'expected_run_id':state['run_id'],'incident_id':'missing'}).status_code==404


def test_worker_is_outside_runtime_lock_and_reset_disabling_and_duplicate_protection(client,monkeypatch):
    configure(client);data(client.post('/api/simulation/step',json={'ticks':10}))
    runtime=client.app.state.runtime
    actual=agent_module.run_autonomous_investigation
    entered,release=Event(),Event()
    def delayed(*args,**kwargs):
        assert not runtime.lock.locked()
        entered.set();assert release.wait(4)
        return actual(*args,**kwargs)
    monkeypatch.setattr(agent_module,'run_autonomous_investigation',delayed)
    run_id=data(client.get('/api/system/state'))['run_id']
    started=data(client.post('/api/agent/investigate',json={'expected_run_id':run_id}))
    try:
        assert entered.wait(2)
        assert client.post('/api/agent/investigate',json={'expected_run_id':run_id}).status_code==409
        assert client.post('/api/shadowtwin/compare',json={'duration_ticks':20,'hypotheses':[{'hypothesis_id':'c','component':'controller','mechanism':'Possible command issue','intervention':'restore_controller_policy'},{'hypothesis_id':'s','component':'solar_sensor','mechanism':'Possible measurement issue','intervention':'use_redundant_solar'}]}).status_code==409
        assert client.get('/api/system/state').status_code==200
        assert client.post('/api/simulation/step',json={'ticks':1}).status_code==200
        data(client.post('/api/agent/auto-mode',json={'enabled':False}))
        new=data(client.post('/api/simulation/reset'))
        assert new['run_id']!=run_id
        assert data(client.get('/api/agent/status'))['latest'] is None
    finally:release.set()
    done=wait_job(client,started['id'])
    assert done['stale'] is True and done['status']=='stale'
    assert done['report']['run_id']==run_id
    assert data(client.get('/api/agent/status'))['latest'] is None


def test_api_investigation_leaves_live_state_schedules_ledgers_and_history_unchanged(client):
    configure(client);data(client.post('/api/simulation/step',json={'ticks':10}))
    runtime=client.app.state.runtime
    before=pickle.dumps((runtime.sim,runtime.baseline,runtime.uncorrected,runtime.ledgers))
    database=list(runtime.store.connection.iterdump())
    started=data(client.post('/api/agent/investigate',json={'expected_run_id':runtime.run_id}))
    done=wait_job(client,started['id'])
    assert done['report'] and done['report']['attempted_experiments']>0
    assert pickle.dumps((runtime.sim,runtime.baseline,runtime.uncorrected,runtime.ledgers))==before
    assert list(runtime.store.connection.iterdump())==database


def test_progress_comes_from_actual_orchestrator_events(client):
    configure(client);data(client.post('/api/simulation/step',json={'ticks':10}))
    run_id=data(client.get('/api/system/state'))['run_id']
    started=data(client.post('/api/agent/investigate',json={'expected_run_id':run_id}))
    done=wait_job(client,started['id'])
    events={event['stage'] for event in done['events']}
    assert {'reviewing_evidence','running_shadowtwin','evaluating_results','decision_recorded','generating_report'}<=events
    assert done['progress_steps']==done['report']['steps']


def test_manager_retention_is_bounded_and_restart_setting_is_off(client):
    manager=client.app.state.agent
    for _ in range(30): manager._new_job('automatic',manager.runtime.run_id,None,0,'skipped','test retention')
    assert len(manager.status()['recent'])==20
    assert manager.status()['automatic_enabled'] is False



def test_disabling_an_active_automatic_job_does_not_cancel_it(client,monkeypatch):
    configure(client);data(client.post('/api/agent/auto-mode',json={'enabled':True}))
    actual=agent_module.run_autonomous_investigation
    entered,release=Event(),Event()
    def delayed(*args,**kwargs):
        entered.set();assert release.wait(4)
        return actual(*args,**kwargs)
    monkeypatch.setattr(agent_module,'run_autonomous_investigation',delayed)
    data(client.post('/api/simulation/step',json={'ticks':10}))
    try:
        assert entered.wait(2)
        active=data(client.get('/api/agent/status'))['active']
        assert active and active['trigger']=='automatic'
        data(client.post('/api/agent/auto-mode',json={'enabled':False}))
        data(client.post('/api/simulation/step',json={'ticks':1}))
    finally:release.set()
    done=wait_job(client,active['id'])
    assert done['report'] and not data(client.get('/api/agent/status'))['automatic_enabled']


def test_initial_unsupported_incident_can_qualify_once_on_new_supported_evidence(client):
    data(client.post('/api/simulation/scenario',json={'config':{'start_hour':17,'communication_delay_ticks':3}}))
    data(client.post('/api/agent/auto-mode',json={'enabled':True}))
    data(client.post('/api/simulation/inject-fault',json={'kind':'inverter','mode':'shutdown','severity':.8,'duration_ticks':100}))
    data(client.post('/api/simulation/step',json={'ticks':10}))
    initial=data(client.get('/api/agent/status'))['recent']
    assert initial and all(job['status']=='skipped' for job in initial)
    original_id=initial[0]['incident_id']
    data(client.post('/api/simulation/inject-attack',json={'attack_type':'controller_compromise','target_component':'controller','severity':.8,'duration_ticks':60}))
    data(client.post('/api/simulation/step',json={'ticks':6}))
    done=automatic_job(client)
    assert done['report'] and done['incident_id']==original_id
    assert done['report']['steps'][0]['intervention_id']=='restore_controller_policy'
    data(client.post('/api/simulation/step',json={'ticks':5}))
    recent=data(client.get('/api/agent/status'))['recent']
    assert len([job for job in recent if job['report_available']])==1



def test_long_historical_evidence_is_bounded_without_mutating_history(client):
    configure(client);data(client.post('/api/simulation/step',json={'ticks':10}))
    runtime=client.app.state.runtime
    incident_id=data(client.get('/api/incidents'))['items'][0]['id']
    original=runtime.store.incident(incident_id)
    extended={**original,'evidence':original['evidence']*300}
    with runtime.store.lock,runtime.store.connection:
        runtime.store.connection.execute('UPDATE incidents SET report=? WHERE id=?',(json.dumps(extended),incident_id))
    before=runtime.store.incident(incident_id)
    started=data(client.post('/api/agent/investigate',json={'expected_run_id':runtime.run_id,'incident_id':incident_id}))
    done=wait_job(client,started['id'])
    assert done['report'] and done['report']['attempted_experiments']>0
    assert '256' in done['evidence_projection']
    assert runtime.store.incident(incident_id)==before
