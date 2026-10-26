"""Public integration: bounded workers, atomic snapshots and unchanged live state."""
from concurrent.futures import ThreadPoolExecutor
import json
import pickle
from threading import Event

from fastapi.testclient import TestClient
import pytest

from app.api.config import ServerSettings
from app.main import create_app
from app.shadowtwin import comparison


@pytest.fixture
def client():
    with TestClient(create_app(ServerSettings(database_path=":memory:", anomaly_model=None, source_model=None, security_model=None))) as connection:
        yield connection


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def body():
    return {"duration_ticks": 20, "hypotheses": [
        {"hypothesis_id":"controller", "component":"controller", "mechanism":"Suspected command inconsistency", "intervention":"restore_controller_policy"},
        {"hypothesis_id":"solar", "component":"solar_sensor", "mechanism":"Suspected measurement inconsistency", "intervention":"use_redundant_solar"}]}


def configure(client, kind="controller"):
    data(client.post('/api/simulation/scenario',json={"config":{"start_hour":17,"communication_delay_ticks":3}}))
    if kind == "controller":
        data(client.post('/api/simulation/inject-attack',json={"attack_type":"controller_compromise","target_component":"controller","severity":0.8,"duration_ticks":100}))
    else:
        data(client.post('/api/simulation/inject-fault',json={"kind":"sensor","mode":"bias","severity":0.8,"duration_ticks":100}))
    data(client.post('/api/simulation/step',json={"ticks":10}))


def test_actual_comparison_serialization_and_isolation(client):
    configure(client)
    runtime = client.app.state.runtime
    before = pickle.dumps((runtime.sim,runtime.baseline,runtime.uncorrected,runtime.ledgers))
    database = list(runtime.store.connection.iterdump())
    request = {**body(),"expected_run_id":runtime.run_id}
    result = data(client.post('/api/shadowtwin/compare',json=request))
    assert result['run_id'] == runtime.run_id and result['snapshot_tick'] == 10 and result['end_tick'] == 30
    assert result['status'] == 'Ranked prospective evidence'
    assert result['hypothesis_ranking'][0]['hypothesis_ids'] == ['controller']
    assert result['historical_source'] == 'Not established'
    assert pickle.dumps((runtime.sim,runtime.baseline,runtime.uncorrected,runtime.ledgers)) == before
    assert list(runtime.store.connection.iterdump()) == database
    for item in result['hypotheses']:
        assert len(item['experiment']['control_telemetry']) == 20
        assert 'comparison_frames' not in item['experiment']
        assert 'energy' not in item['experiment']
    encoded = json.dumps(result,allow_nan=False)
    assert all(token not in encoded for token in ('ground_truth','target_component','_schedule','training_labels'))


@pytest.mark.parametrize('change', [
    {"duration_ticks":True},{"duration_ticks":0},{"duration_ticks":1.5},{"duration_ticks":121},
    {"hypotheses":[]},{"unexpected":"value"},{"snapshot":{"tick":10}},
])
def test_invalid_requests_leave_runtime_unchanged(client,change):
    before = data(client.get('/api/system/state'))
    response = client.post('/api/shadowtwin/compare',json={**body(),**change})
    assert response.status_code == 422
    assert data(client.get('/api/system/state')) == before


@pytest.mark.parametrize('change', [
    {"intervention":"repair_inverter"},{"component":"inverter"},{"component":"communication"},
    {"mechanism":" "},{"hypothesis_id":""},{"ground_truth":"secret"},
])
def test_invalid_hypotheses_are_rejected(client,change):
    request=body()
    request['hypotheses'][0].update(change)
    assert client.post('/api/shadowtwin/compare',json=request).status_code == 422


def test_duplicate_and_excessive_batches_and_horizon(client):
    request=body()
    request['hypotheses']=[request['hypotheses'][0]]*2
    assert client.post('/api/shadowtwin/compare',json=request).status_code == 422
    request['hypotheses']*=4
    assert client.post('/api/shadowtwin/compare',json=request).status_code == 422
    client.app.state.runtime.settings.max_ticks=10
    assert client.post('/api/shadowtwin/compare',json=body()).status_code == 422


def test_equivalent_explanations_and_missing_evidence_remain_inconclusive(client):
    configure(client,'sensor')
    request=body()
    first=request['hypotheses'][1]
    request['hypotheses']=[first,{**first,'hypothesis_id':'solar_other','mechanism':'Possible sensor manipulation'}]
    result=data(client.post('/api/shadowtwin/compare',json=request))
    assert result['status']=='Inconclusive'
    assert result['tied_or_tradeoff_groups']==[['solar','solar_other']]
    assert result['recorded_evidence']==[]
    data(client.post('/api/simulation/reset'))
    result=data(client.post('/api/shadowtwin/compare',json=body()))
    assert result['status']=='Inconclusive'


def test_stale_run_and_unknown_incident_are_clear_errors(client):
    assert client.post('/api/shadowtwin/compare',json={**body(),'expected_run_id':'old-run'}).status_code==409
    assert client.post('/api/shadowtwin/compare',json={**body(),'incident_id':'missing'}).status_code==404


def test_reset_and_parallel_requests_during_worker_are_safe(client,monkeypatch):
    configure(client)
    runtime=client.app.state.runtime
    old=runtime.run_id
    entered,release=Event(),Event()
    original=comparison.compare_hypotheses
    def slow(*args,**kwargs):
        assert not runtime.lock.locked()
        entered.set()
        assert release.wait(5)
        return original(*args,**kwargs)
    # main imports the public function inside the endpoint.
    monkeypatch.setattr('app.shadowtwin.compare_hypotheses',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(client.post,'/api/shadowtwin/compare',json={**body(),'expected_run_id':old})
        try:
            assert entered.wait(5)
            assert client.post('/api/shadowtwin/compare',json=body()).status_code==409
            assert data(client.post('/api/simulation/step',json={'ticks':1}))['next_tick']==11
            fresh=data(client.post('/api/simulation/reset'))
            assert fresh['run_id']!=old
        finally:
            release.set()
        result=data(future.result(timeout=10))
    assert result['run_id']==old and result['current_run_id']==fresh['run_id'] and result['run_changed']
    assert result['snapshot_tick']==10
    assert runtime.sim.tick==0


def test_labels_cannot_influence_public_results(client):
    configure(client)
    first=data(client.post('/api/shadowtwin/compare',json=body()))
    runtime=client.app.state.runtime
    runtime.sim.attacks._records[0].update(target_component='SECRET_SOURCE',attack_type='SECRET_FAMILY')
    second=data(client.post('/api/shadowtwin/compare',json=body()))
    assert first['hypothesis_ranking']==second['hypothesis_ranking']
    assert first['hypotheses']==second['hypotheses']
    assert 'SECRET_' not in json.dumps(second)


def test_internal_unsupported_status_is_preserved_in_response(client,monkeypatch):
    original=comparison.compare_hypotheses
    def unsupported(*args,**kwargs):
        result=original(*args,**kwargs)
        item=result['hypotheses'][0]
        item.update(experiment_status='unsupported',ranking_position=None,intervention_rank=None,experiment=None)
        return result
    monkeypatch.setattr('app.shadowtwin.compare_hypotheses',unsupported)
    result=data(client.post('/api/shadowtwin/compare',json=body()))
    assert result['hypotheses'][0]['experiment_status']=='unsupported'
    assert result['hypotheses'][0]['experiment'] is None


def test_current_and_historical_incident_context_with_real_models():
    with TestClient(create_app(ServerSettings(database_path=':memory:'))) as client:
        configure(client)
        data(client.post('/api/simulation/step',json={'ticks':30}))
        incident=data(client.get('/api/incidents'))['items'][0]['id']
        result=data(client.post('/api/shadowtwin/compare',json={**body(),'incident_id':incident}))
        assert result['incident_run_id']==result['run_id'] and not result['historical_incident']
        data(client.post('/api/simulation/reset'))
        historical=data(client.post('/api/shadowtwin/compare',json={**body(),'incident_id':incident}))
        assert historical['historical_incident'] and historical['incident_run_id']!=historical['run_id']
        assert historical['recorded_evidence']==[]
        assert data(client.get('/api/incidents'))['total']>=1
