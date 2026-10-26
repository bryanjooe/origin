# Stage 1 simulation contract

## Time, physics, and units

One tick is 60 simulated seconds by default, configurable through `GridConfig`.
Rows describe the interval beginning at `tick * tick_seconds`; battery SOC and
stored energy are end-of-interval values. Controller SOC input is measured at the
start of the interval. Default start time is 10:00, with a repeated 24-hour day.
Power is kW, energy is kWh, time/latency/age is seconds, voltage is V, current is A,
SOC is percent, irradiance is normalized [0, 1]. Battery power is positive for
discharge and negative for charge. No grid import, export market, or fossil backup.

PV output = rated capacity × daylight sine × bounded correlated cloud factor.
Daylight runs from 06:00 to 18:00. Cloud variation uses seeded pseudorandom noise.
Demand has a positive base plus morning/evening peaks and bounded variation.
These are illustrative synthetic signals, not calibrated field measurements.
PV voltage uses a fixed nominal DC bus voltage; current = 1000 × power / voltage.
Reported current is derived from the possibly faulty power reading and nominal
voltage, so it is not an independent redundant measurement.

Controller dispatch uses only the latest received packet and applied operating
configuration. It aims to meet AC demand using solar first, charging on surplus
and discharging on deficit. It records packet inputs, nominal and issued commands,
operating rule, applied reserve, and discharge limit each tick. With no received
packet it issues zero dispatch/output. Sensor measurements include small Gaussian
noise. Expected PV is an idealized reference available in this simulation.

For interval length dt in hours:

- Charging: stored-energy increment = charge kW × charge efficiency × dt.
- Discharging: stored-energy decrement = discharge kW / discharge efficiency × dt.
- Physical power limits and available energy constrain dispatch independently of
  the controller. Charge cannot exceed available PV; no grid charging occurs.
- SOC stays in [physical reserve, 100%]. The reserve defaults to 10%, but can be 0.
- DC bus power = PV + signed battery power.
- Inverter AC output = min(request target, DC bus × actual efficiency, AC rating).
- Delivered AC = min(inverter AC output, current physical demand).
- Unmet demand = demand − delivered AC.

Per-interval energy balance:

```text
PV kWh = delivered AC kWh + excess AC kWh + unused DC kWh
       + inverter loss kWh + battery loss kWh + battery stored-energy change kWh
```

`curtailed_dc_kw` denotes unused DC bus power, which can include unnecessary
battery discharge under a fault; it is not exclusively curtailed PV. Excess AC is
separately accounted when stale commands exceed current demand. Inverter losses
are DC consumed minus AC produced. These quantities prevent counting energy lost
as delivered. Initial battery energy is an explicit stored-energy boundary term;
served load must not be described as entirely renewable-generated-during-run.
Stage 1 does not track the provenance of stored energy or estimate fault-attributed
loss; those sustainability analyses are deferred.

## Communication

One aggregate PV/SOC/demand packet is generated per tick with `source_tick`.
Baseline delay and loss are configurable. Messages are delivered when their due
tick arrives. An older delayed packet cannot overwrite a newer accepted packet.
`message_age_seconds` measures the age of the packet actually used by the
controller, or null before any packet arrives. `communication_latency_seconds`
is the currently configured transport delay for a newly generated packet, not a
measurement of a dropped packet's actual arrival time. `packet_dropped` applies to
the current outgoing packet. Stale mode reuses the last received values and source
timestamp. No sockets, network attacks, or real device operations are used.

## Fault modes

All faults have a start tick, positive integer duration and severity in (0, 1].
Active interval is `[start, start + duration)`. Starts in the past and overlapping
faults are rejected. Severity is a dimensionless scenario parameter, not a
probability of fault or model confidence.

| Family | Modes | Implemented perturbation |
|---|---|---|
| Sensor | bias, drift | Add up to severity × PV rating; drift ramps over duration |
| Sensor | noise | Gaussian noise with stddev severity × PV rating; floor at zero |
| Sensor | stuck | Hold last pre-fault reading; at tick 0 hold first reading |
| Sensor | soc_bias | Add severity × 60 percentage points, clipped to [0, 100] |
| Communication | delay | Add ceil(8 × severity) ticks to baseline delay |
| Communication | drop | Seeded drop probability equal to severity, in addition to baseline loss |
| Communication | stale | Suppress all new messages during the fault |
| Communication | corrupt | Add 2 × severity × PV rating to transmitted solar value |
| Controller | wrong_dispatch | Request charging at severity × max charge rate, irrespective of normal dispatch |
| Firmware | discharge_limit | Multiply configured controller discharge limit by (1 − severity) |
| Firmware | reserve_threshold | Raise controller reserve toward 100% proportional to severity |
| Inverter | derate | Multiply requested target by (1 − severity) |
| Inverter | shutdown | Zero AC output |
| Inverter | efficiency | Multiply efficiency by (1 − 0.8 × severity) |
| Inverter | delay | Blend current target with previous target using severity as lag weight |

Stuck, stale, and shutdown are discrete behaviors; severity does not scale them.
Inverter delay is a one-step lag approximation. Firmware integrity is a simulated
comparison against the intended configuration, not cryptographic attestation.

Expiry restores the component automatically. Already queued delayed packets can
remain after expiry, but freshness ordering prevents timestamp rollback. Correction
immediately cancels faults and scheduled faults, flushes transport messages, and
restores component behavior without resetting energy or time. Scenario truth retains
the original planned duration plus cancellation tick. Recovery need not restore the
same battery energy as a fault-free counterfactual. Reset removes all records and
returns to the initial state; resetting with the same seed reproduces the run.
Weather, measurement, and communication RNG streams are separate, preserving
identical weather/demand for paired seeded baseline and faulty scenarios.

## Ground truth and topology

Fault schedules and severity live in `FaultEngine`, exported only as scenario
metadata. Telemetry exposes measurements, physical references, configuration
integrity, message metadata and controller logs, but not fault labels. Physical
references are simulation oracle values; later model design must explicitly decide
which independent measurements could supply equivalent residuals. Stage 1 has no
feature builder, labels for training, classifier, anomaly scores, or fabricated
component health predictions.

The NetworkX graph distinguishes physical, measurement, information, configuration,
and command edges. Feedback cycles are intentional (battery → sensor → controller
→ battery). Descendants identify potential dependencies only. Every edge includes
a documented dependency and `suspected=false`; no inferred incident propagation
or causal attribution exists at this stage.

## Validation and remaining stages

Tests cover day/night generation, normal measurements, battery boundaries, limits,
conversion losses, interval energy conservation across all fault modes, packet
timestamp order, scheduled faults, recovery, correction, reset, seeded replay,
ground-truth separation, topology, validation errors and CLI exports.

Later stages will add normal-baseline ML, scenario-level held-out classification,
evidence-grounded diagnosis, API synchronization, persistence, dashboard, and
sustainability comparisons. None is required to run this Stage 1 simulator.
