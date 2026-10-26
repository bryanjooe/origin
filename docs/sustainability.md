# Stage 5 sustainability accounting

The API runs three synchronized simulators with the same configuration, seed,
initial energy and number of ticks:

1. **Baseline:** no injected faults or correction.
2. **Faulty uncorrected:** all requested injections retain their planned durations.
3. **Operated:** requested injections plus user-requested simulated correction.

Independent RNG streams keep weather and demand identical across the three runs.
Correction only affects the operated simulator. Before any correction, operated and
faulty results match. Afterward battery states can diverge; these are whole-horizon
comparisons, not equal-SOC snapshots or an isolated post-correction efficiency test.

## Total energy balance

Each ledger integrates actual kW over `tick_seconds / 3600` and separately tracks
losses and stored-energy change:

```text
solar generated = delivered AC + excess AC + unused DC
                + inverter losses + battery losses + battery energy change
```

`energy_balance_residual_kwh` exposes numerical closure of this equation. Demand
served plus unmet demand equals total demand. Actual solar, physical dispatch and
conversion values are used for these **physical simulation metrics only**, not
added to inference features. Battery efficiencies use actual energy ratios and are
null until a corresponding charge/discharge occurs. Configured round-trip efficiency
is charge efficiency × discharge efficiency; it is not an observed complete cycle.

## Renewable provenance

Initial stored energy is explicitly **unknown provenance**, not newly generated
renewable energy. The ledger maintains renewable and unknown energy pools in the
battery. Charging uses current solar only, with charge-efficiency loss. Discharge
withdraws from both pools proportionally and applies discharge efficiency. Solar
and battery contributions then mix proportionally on the DC bus before conversion,
delivery, excess AC and curtailment are allocated.

Thus a night-time run can serve demand from initial storage while reporting zero
renewable delivery. Solar energy charged during the run can be tagged and delivered
later. Remaining renewable stored energy is not counted as delivered. The independent
renewable balance is also exposed:

```text
solar generated = renewable delivered + renewable excess AC + renewable unused DC
                + renewable inverter/battery losses + remaining renewable storage
```

`renewable_energy_balance_residual_kwh` checks this second equation. These are
accounting assumptions about synthetic energy mixing, not measured provenance.

`unused_dc_kwh` can include wasted battery discharge. `solar_curtailed_kwh` allocates
only the current PV share of unused DC; `renewable_unused_dc_kwh` also includes
tagged stored-renewable energy wasted after discharge. `solar_capture_fraction`
is one minus direct solar curtailment/generated solar; it includes energy entering
storage/conversion, not just useful delivered AC. `renewable_delivery_fraction_of_generated`
is delivered tagged renewable/generated solar. Both are null with zero generation.

## Counterfactual estimates

- `signed_baseline_minus_faulty_delivery_kwh` is baseline delivery minus hypothetical
  uncorrected delivery over the equal horizon.
- `estimated_fault_delivery_loss_kwh` clips that signed value at zero; the signed
  quantity remains available so an improvement cannot be hidden as a positive loss.
- `estimated_correction_delivery_gain_kwh` is operated minus uncorrected delivery;
  it can be negative if a correction/changed storage state reduces delivery.

These estimates combine all modeled effects of the chosen scenario. They are not
measured causal attribution, field energy savings, or guarantees that a diagnosis
is correct. No emissions factor is configured, and the API makes no carbon-saving
claim. Faults and corrections remain software-only.

Ledgers reset with a new scenario. The latest totals and assumptions are returned by
`GET /api/metrics/sustainability` and checkpointed in persisted scenario metadata.
Tests exercise day/night storage, sensor/controller/firmware/inverter faults,
physical and renewable conservation, initial-unknown energy and null efficiencies.
