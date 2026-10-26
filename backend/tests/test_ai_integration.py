from __future__ import annotations

import time
import threading

import httpx
import pytest

from app.ai.provider import (
    HTTPAnalysisProvider,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderRequestFailed,
    ProviderTimedOut,
    UnavailableAnalysisProvider,
)
from app.api.schemas import AIAnalysisOutput
from test_api import create_run, make_client


VALID_OUTPUT_FIXTURE = {
    "schema_version": "1",
    "summary": "Test fixture output for adapter contract coverage.",
    "findings": [
        {
            "component": "solar",
            "finding": "The fixture verifies a structurally valid response.",
            "evidence_refs": ["telemetry.tick:1"],
        }
    ],
}


class FixedProvider:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def analyze(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response


def wait_for_terminal(client, analysis_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/analyses/{analysis_id}")
        assert response.status_code == 200, response.text
        record = response.json()
        if record["status"] in {"completed", "failed"}:
            return record
        time.sleep(0.01)
    raise AssertionError("analysis job did not reach a terminal state")


def submit(client, run_id, *, key="analysis-request-0001", start=0, end=None):
    return client.post(
        f"/api/v1/runs/{run_id}/analyses",
        headers={"Idempotency-Key": key},
        json={"start_tick": start, "end_tick": end},
    )


def test_successful_job_uses_only_frozen_typed_observations_and_is_idempotent():
    provider = FixedProvider({"model_name": "fixture-provider", "model_version": "test-v1", "result": VALID_OUTPUT_FIXTURE})
    with make_client(analysis_provider=provider) as client:
        run = create_run(client, seed=77)
        run_id = run["run_id"]
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 4}).status_code == 200
        response = submit(client, run_id, start=1, end=3)
        assert response.status_code == 202, response.text
        job = response.json()
        completed = wait_for_terminal(client, job["analysis_id"])

        assert completed["status"] == "completed"
        assert completed["model_name"] == "fixture-provider"
        assert completed["model_version"] == "test-v1"
        assert completed["result"] == VALID_OUTPUT_FIXTURE
        assert completed["started_at"] and completed["completed_at"]
        assert len(provider.calls) == 1
        sent = provider.calls[0].model_dump(mode="json")
        assert sent["window"] == {"start_tick": 1, "end_tick": 3}
        assert [row["tick"] for row in sent["telemetry"]] == [1, 2]
        assert [row["tick"] for row in sent["controller_logs"]] == [1, 2]
        assert all("fault" not in row and "severity" not in row for row in sent["telemetry"])
        assert "ground_truth" not in str(sent).lower()
        for oracle_field in (
            "expected_solar_kw", "actual_solar_kw", "battery_soc_pct",
            "battery_energy_kwh", "battery_delta_kwh", "battery_loss_kwh",
            "inverter_loss_kw", "curtailed_dc_kw", "excess_ac_kw",
            "config_integrity_ok",
        ):
            assert oracle_field not in str(sent)
        assert len(sent["telemetry"]) == len(sent["controller_logs"])

        duplicate = submit(client, run_id, start=1, end=3)
        assert duplicate.status_code == 202
        assert duplicate.json()["analysis_id"] == job["analysis_id"]
        assert len(provider.calls) == 1

        conflict = submit(client, run_id, start=0, end=3)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_key_reused"
        assert len(provider.calls) == 1


def test_job_snapshot_does_not_include_ticks_added_while_provider_is_running():
    entered = threading.Event()
    release = threading.Event()

    class SlowProvider(FixedProvider):
        def analyze(self, request):
            self.calls.append(request)
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test provider release timed out")
            return {"result": VALID_OUTPUT_FIXTURE}

    provider = SlowProvider()
    try:
        with make_client(analysis_provider=provider) as client:
            run = create_run(client)
            run_id = run["run_id"]
            client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 3})
            submitted = submit(client, run_id, start=0, end=2)
            assert submitted.status_code == 202
            assert entered.wait(timeout=1)
            assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 2}).status_code == 200
            release.set()
            terminal = wait_for_terminal(client, submitted.json()["analysis_id"])
            assert terminal["status"] == "completed"
            assert [row.tick for row in provider.calls[0].telemetry] == [0, 1]
            assert [row.tick for row in provider.calls[0].controller_logs] == [0, 1]
    finally:
        release.set()


def test_unavailable_provider_creates_failed_job_without_fabricating_result():
    with make_client(analysis_provider=UnavailableAnalysisProvider()) as client:
        run = create_run(client)
        run_id = run["run_id"]
        client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 1})
        response = submit(client, run_id)
        assert response.status_code == 202
        record = wait_for_terminal(client, response.json()["analysis_id"])
        assert record["status"] == "failed"
        assert record["failure_code"] == "provider_unavailable"
        assert record["result"] is None
        assert "prediction" not in response.text.lower()


def test_invalid_provider_output_is_stored_as_failure_not_returned_as_result():
    provider = FixedProvider({
        "model_name": "fixture-provider",
        "model_version": "test-v1",
        "result": {
            "schema_version": "1",
            "summary": "invalid test fixture",
            "findings": [{"component": "not-a-topology-node", "finding": "x", "evidence_refs": ["tick:0"]}],
        },
    })
    with make_client(analysis_provider=provider) as client:
        run = create_run(client)
        client.post(f"/api/v1/runs/{run['run_id']}/advance", json={"ticks": 1})
        response = submit(client, run["run_id"])
        record = wait_for_terminal(client, response.json()["analysis_id"])
        assert record["status"] == "failed"
        assert record["failure_code"] == "provider_invalid_response"
        assert record["result"] is None


@pytest.mark.parametrize(
    ("provider_error", "failure_code"),
    [
        (ProviderTimedOut(), "provider_timeout"),
        (ProviderInvalidResponse(), "provider_invalid_response"),
        (ProviderRequestFailed(), "provider_request_failed"),
    ],
)
def test_provider_timeouts_and_malformed_responses_become_failed_jobs(provider_error, failure_code):
    with make_client(analysis_provider=FixedProvider(error=provider_error)) as client:
        run = create_run(client)
        client.post(f"/api/v1/runs/{run['run_id']}/advance", json={"ticks": 1})
        response = submit(client, run["run_id"])
        record = wait_for_terminal(client, response.json()["analysis_id"])
        assert record["status"] == "failed"
        assert record["failure_code"] == failure_code
        assert record["result"] is None


def test_http_provider_retries_transient_failure_once_and_sends_no_hidden_fields():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"detail": "temporary"})
        return httpx.Response(200, json={"model_name": "team-model", "model_version": "rev-a", "result": VALID_OUTPUT_FIXTURE})

    provider = HTTPAnalysisProvider(
        "http://ai.test",
        api_key="test-secret",
        max_retries=1,
        _client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs),
        _sleep=sleeps.append,
    )
    from app.ai.contracts import (
        AnalysisInferenceRequest,
        InferenceControllerLog,
        InferenceTelemetryRow,
    )

    request = AnalysisInferenceRequest(
        analysis_id="test-analysis",
        simulation_run_id="test-run",
        window={"start_tick": 0, "end_tick": 1},
        telemetry=[InferenceTelemetryRow(
            tick=0, elapsed_seconds=0.0, hour=10.0,
            measured_solar_kw=0.0, measured_soc_pct=60.0,
            measured_solar_voltage_v=0.0, measured_solar_current_a=0.0,
            demand_kw=7.0, delivered_kw=0.0, unmet_demand_kw=7.0,
        )],
        controller_logs=[InferenceControllerLog(
            tick=0, elapsed_seconds=0.0, controller_inputs=None,
            controller_rule="await_telemetry", controller_command_kw=0.0,
            nominal_command_kw=0.0, applied_reserve_soc_pct=10.0,
            applied_discharge_limit_kw=5.0, inverter_requested_kw=0.0,
            inverter_actual_kw=0.0, message_source_tick=None,
            message_age_seconds=None, communication_latency_seconds=0.0,
            packet_dropped=False, telemetry_available=False,
        )],
    )
    result = provider.analyze(request)
    assert result.model_name == "team-model"
    assert result.result == AIAnalysisOutput.model_validate(VALID_OUTPUT_FIXTURE)
    assert len(calls) == 2
    assert sleeps == [0.1]
    assert calls[1].headers["Authorization"] == "Bearer test-secret"
    body = calls[1].read().decode()
    assert "scenario_ground_truth" not in body and "fault_scenarios" not in body
    for oracle_field in (
        "expected_solar_kw", "actual_solar_kw", "battery_soc_pct",
        "battery_energy_kwh", "battery_delta_kwh", "battery_loss_kwh",
        "inverter_loss_kw", "curtailed_dc_kw", "excess_ac_kw",
        "config_integrity_ok",
    ):
        assert oracle_field not in body


def test_http_provider_bounds_timeout_retries_and_does_not_retry_client_errors():
    timeout_calls = []
    sleeps = []

    def timeout_handler(request):
        timeout_calls.append(request)
        raise httpx.ReadTimeout("simulated timeout", request=request)

    provider = HTTPAnalysisProvider(
        "http://ai.test",
        max_retries=1,
        _client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(timeout_handler), **kwargs),
        _sleep=sleeps.append,
    )
    from app.ai.contracts import AnalysisInferenceRequest, AnalysisWindow

    request = AnalysisInferenceRequest.model_construct(
        analysis_id="test-analysis",
        simulation_run_id="test-run",
        window=AnalysisWindow.model_construct(start_tick=0, end_tick=1),
        telemetry=[],
        controller_logs=[],
    )
    with pytest.raises(ProviderTimedOut):
        provider.analyze(request)
    assert len(timeout_calls) == 2
    assert sleeps == [0.1]

    client_error_calls = []

    def client_error_handler(request):
        client_error_calls.append(request)
        return httpx.Response(400, json={"detail": "bad request"})

    client_error_provider = HTTPAnalysisProvider(
        "http://ai.test",
        max_retries=3,
        _client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(client_error_handler), **kwargs),
        _sleep=lambda _delay: pytest.fail("client errors must not be retried"),
    )
    with pytest.raises(ProviderRequestFailed):
        client_error_provider.analyze(request)
    assert len(client_error_calls) == 1


def test_http_provider_retries_rate_limit_with_a_hard_attempt_bound():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"detail": "limited"})

    provider = HTTPAnalysisProvider(
        "http://ai.test",
        max_retries=2,
        _client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs),
        _sleep=sleeps.append,
    )
    from app.ai.contracts import AnalysisInferenceRequest, AnalysisWindow

    request = AnalysisInferenceRequest.model_construct(
        analysis_id="test-analysis",
        simulation_run_id="test-run",
        window=AnalysisWindow.model_construct(start_tick=0, end_tick=1),
        telemetry=[],
        controller_logs=[],
    )
    with pytest.raises(ProviderRateLimited):
        provider.analyze(request)
    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]

