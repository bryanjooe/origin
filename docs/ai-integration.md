# AI component integration contract

## Integration status

The repository does not contain the AI team's model package, deployed endpoint, or a
team-approved input/output schema. This document and the v1 contract below are the
backend's proposed connection point, not evidence that real inference is available.
The default provider is disabled. A submitted job ends with `provider_unavailable`
until a service URL or local adapter is supplied; the backend never returns a canned
prediction. The AI team should confirm the open decisions at the end of this document
before connecting a deployment.

## Provider-independent adapter

The integration boundary is `AnalysisProvider.analyze(AnalysisInferenceRequest) ->
ProviderAnalysisResponse` in `backend/app/ai/contracts.py`. Any local model wrapper can
implement that protocol. The default HTTP adapter in `backend/app/ai/provider.py`
sends the same contract to:

```text
POST {TRACEX_AI_SERVICE_URL}/v1/analyze
Content-Type: application/json
Authorization: Bearer {TRACEX_AI_SERVICE_API_KEY}  # only when configured
```

The request body contains only `schema_version`, `analysis_id`, `simulation_run_id`,
the half-open `window`, typed `telemetry` rows, and corresponding `controller_logs`.
Unknown fields are rejected. The backend constructs dedicated AI observation DTOs
from the general simulator telemetry. It excludes idealized/actual PV oracle channels,
internal battery state/energy balances, inverter loss/curtailment summaries, and the
simulated firmware-integrity flag, as well as configuration, fault schedules, replay
commands, incident labels, scenario records, `scenario_ground_truth.json`, simulator
events, and future ticks.
The exclusive `end_tick` must be no greater than the run's current tick when the
snapshot is captured; default `end_tick` freezes the then-current tick. The requested
window is limited to the existing 2,000-tick response bound. Later run advances do
not mutate a queued job's frozen input.

Contract outline:

```json
{
  "schema_version": "1",
  "analysis_id": "<job UUID>",
  "simulation_run_id": "<run UUID>",
  "window": {"start_tick": 10, "end_tick": 12},
  "telemetry": [
    {
      "tick": 10, "elapsed_seconds": 600.0, "hour": 10.17,
      "measured_solar_kw": 4.2, "measured_soc_pct": 61.0,
      "measured_solar_voltage_v": 400.0, "measured_solar_current_a": 10.5,
      "demand_kw": 7.0, "delivered_kw": 6.8, "unmet_demand_kw": 0.2
    },
    {"tick": 11, "elapsed_seconds": 660.0, "hour": 10.18, "measured_solar_kw": 4.3, "measured_soc_pct": 61.0, "measured_solar_voltage_v": 400.0, "measured_solar_current_a": 10.75, "demand_kw": 7.0, "delivered_kw": 7.0, "unmet_demand_kw": 0.0}
  ],
  "controller_logs": [
    {
      "tick": 10, "elapsed_seconds": 600.0, "controller_inputs": null,
      "controller_rule": "await_telemetry", "controller_command_kw": 0.0,
      "nominal_command_kw": 0.0, "applied_reserve_soc_pct": 10.0,
      "applied_discharge_limit_kw": 5.0, "inverter_requested_kw": 0.0,
      "inverter_actual_kw": 0.0, "message_source_tick": null,
      "message_age_seconds": null, "communication_latency_seconds": 0.0,
      "packet_dropped": false, "telemetry_available": false
    },
    {"tick": 11, "elapsed_seconds": 660.0, "controller_inputs": {"source_tick": 10, "solar_kw": 4.2, "soc_pct": 61.0, "demand_kw": 7.0}, "controller_rule": "renewable_first", "controller_command_kw": 0.0, "nominal_command_kw": 0.0, "applied_reserve_soc_pct": 10.0, "applied_discharge_limit_kw": 5.0, "inverter_requested_kw": 4.0, "inverter_actual_kw": 4.0, "message_source_tick": 10, "message_age_seconds": 60.0, "communication_latency_seconds": 0.0, "packet_dropped": false, "telemetry_available": true}
  ]
}
```

Each array must exactly cover the window in tick order. The schemas are
`InferenceTelemetryRow` and `InferenceControllerLog` in `backend/app/ai/contracts.py`.
No labels, truth files, simulator oracle fields, or post-window rows are accepted as
model inputs. The numeric values above illustrate shape only; they are not model
outputs or benchmark results.

The provider returns this envelope:

```json
{
  "model_name": "<optional provider-supplied model name>",
  "model_version": "<optional provider-supplied version>",
  "result": {
    "schema_version": "1",
    "summary": "<required summary>",
    "findings": [
      {
        "component": "<existing topology component id>",
        "finding": "<required evidence-based text>",
        "evidence_refs": ["telemetry.tick:10"]
      }
    ]
  }
}
```

The result is validated again before persistence. Extra fields are forbidden;
components must exist in the existing dependency topology; evidence references may
not name ground-truth or fault-scenario data. The backend does not assign confidence,
fault classes, or accuracy semantics that the AI team has not defined.

## Job API and failure behavior

- `POST /api/v1/runs/{run_id}/analyses` with JSON `{"start_tick": 10, "end_tick": 12}`
  and a stable `Idempotency-Key` header (8–128 characters) returns `202` and an
  `analysis_id`/status path.
- `GET /api/v1/analyses/{analysis_id}` returns `pending`, `running`, `completed`, or
  `failed`, timestamps, optional provider/model versions, validated result, and
  sanitized failure code/message.
- Replaying the same idempotency key for the same run/window returns the original job.
  Reusing it for a different run/window returns `409`. A failed job is not silently
  resubmitted under the same key; use a new key for an intentional retry.
- Jobs execute in a bounded in-process worker pool. A full queue produces a persisted
  failed job (`worker_capacity`); a process restart marks unfinished jobs
  `worker_interrupted`. Use one API worker process as documented for the simulator.
- `TRACEX_AI_TIMEOUT_SECONDS` bounds each provider call. Transient connection/time-out,
  HTTP 408/429, and 5xx failures receive up to `TRACEX_AI_MAX_RETRIES` retries
  (0–3). Other 4xx responses and malformed output are not retried. Failures become
  failed jobs; provider response bodies, credentials, and stack traces are not
  returned to API clients.

The current backend does not authenticate analysis submission/status routes. Keep
them on a trusted network until the project defines a general API identity and access
policy. The optional provider bearer credential is sent only server-to-server.

## Configuration and local adapters

Add these names to the server environment; do not commit credentials:

- `TRACEX_AI_SERVICE_URL`: optional HTTP service base URL. Unset disables inference.
- `TRACEX_AI_SERVICE_API_KEY`: optional provider bearer credential.
- `TRACEX_AI_TIMEOUT_SECONDS`: request timeout, default 10 (maximum 120).
- `TRACEX_AI_MAX_RETRIES`: transient retries, default 1 (maximum 3).
- `TRACEX_AI_WORKERS`: worker count, default 2 (maximum 8).
- `TRACEX_AI_QUEUE_SIZE`: queued jobs beyond workers, default 8 (maximum 64).

For a local model, implement `AnalysisProvider` and inject it through the
`create_app(..., analysis_provider=your_adapter)` factory. The adapter receives only
the validated request above and must return `ProviderAnalysisResponse` (or an object
that validates against it). Do not import simulator internals or fault-injection
records into that adapter.

## Decisions for the AI team

Confirm before deployment:

1. Whether `/v1/analyze` and the envelope names above match the intended service, or
   provide the actual route and response shape.
2. Whether this telemetry/controller-log feature set is sufficient and which
   prediction-time fields the model requires. Any added field must be audited for
   future information and hidden labels first.
3. Model output semantics, including whether findings are observations, candidate
   fault classes, or localized components, and what evidence references mean.
4. Authentication scheme, deployment URL, operational timeout/rate limits, and the
   model/version metadata the service can return.
5. Whether analysis jobs need a durable external queue for the intended deployment.

The mocked provider tests use clearly labeled fixtures only. They verify transport,
validation, retries, error handling, idempotency, and truth isolation; they do not
evaluate a model or establish any fault-localization performance.
