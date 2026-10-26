# Stage 5 security telemetry realism audit

All values are mean per-run observed telemetry rates over active fault/attack ticks, or full normal runs. Data is from seeded synthetic simulations only. Each attack type / stealth cell contains 27 independent runs; each fault mode contains 27 runs; normal contains 540 runs. This report groups measured telemetry only and does not feed labels into the feature pipeline.

| Group | Runs | Auth invalid | Sequence anomaly | Hash mismatch | Solar disagreement | Battery disagreement | Policy violation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| normal | 540 | 0.010 | 0.000 | 0.000 | 0.038 | 0.033 | 0.000 |
| communication/corrupt | 27 | 0.013 | 0.000 | 0.000 | 0.030 | 0.031 | 0.000 |
| communication/delay | 27 | 0.007 | 0.000 | 0.000 | 0.031 | 0.034 | 0.000 |
| communication/drop | 27 | 0.007 | 0.000 | 0.000 | 0.034 | 0.028 | 0.000 |
| communication/stale | 27 | 0.000 | 0.000 | 0.000 | 0.042 | 0.042 | 0.000 |
| controller/wrong_dispatch | 27 | 0.008 | 0.000 | 0.000 | 0.041 | 0.031 | 0.981 |
| firmware/discharge_limit | 27 | 0.007 | 0.000 | 1.000 | 0.029 | 0.039 | 0.000 |
| firmware/reserve_threshold | 27 | 0.006 | 0.000 | 1.000 | 0.018 | 0.034 | 0.000 |
| inverter/delay | 27 | 0.012 | 0.000 | 0.000 | 0.032 | 0.033 | 0.000 |
| inverter/derate | 27 | 0.013 | 0.000 | 0.000 | 0.026 | 0.031 | 0.000 |
| inverter/efficiency | 27 | 0.009 | 0.000 | 0.000 | 0.039 | 0.029 | 0.000 |
| inverter/shutdown | 27 | 0.009 | 0.000 | 0.000 | 0.041 | 0.028 | 0.000 |
| sensor/bias | 27 | 0.011 | 0.000 | 0.000 | 1.000 | 0.036 | 0.000 |
| sensor/drift | 27 | 0.014 | 0.000 | 0.000 | 0.952 | 0.027 | 0.000 |
| sensor/noise | 27 | 0.008 | 0.000 | 0.000 | 0.930 | 0.034 | 0.000 |
| sensor/soc_bias | 27 | 0.008 | 0.000 | 0.000 | 0.030 | 1.000 | 0.000 |
| sensor/stuck | 27 | 0.009 | 0.000 | 0.000 | 0.709 | 0.045 | 0.000 |
| actuator_abuse/moderate | 27 | 0.010 | 0.000 | 0.000 | 0.031 | 0.038 | 0.000 |
| actuator_abuse/naive | 27 | 0.007 | 0.000 | 0.000 | 0.026 | 0.035 | 0.000 |
| actuator_abuse/stealthy | 27 | 0.011 | 0.000 | 0.000 | 0.040 | 0.040 | 0.000 |
| communication_degradation/moderate | 27 | 0.011 | 0.000 | 0.000 | 0.057 | 0.039 | 0.000 |
| communication_degradation/naive | 27 | 0.005 | 0.000 | 0.000 | 0.022 | 0.038 | 0.000 |
| communication_degradation/stealthy | 27 | 0.010 | 0.399 | 0.000 | 0.025 | 0.029 | 0.000 |
| controller_compromise/moderate | 27 | 0.010 | 0.000 | 0.000 | 0.014 | 0.036 | 1.000 |
| controller_compromise/naive | 27 | 0.011 | 0.000 | 0.000 | 0.033 | 0.029 | 1.000 |
| controller_compromise/stealthy | 27 | 0.009 | 0.000 | 0.000 | 0.031 | 0.038 | 1.000 |
| firmware_tampering/moderate | 27 | 0.010 | 0.000 | 1.000 | 0.033 | 0.033 | 0.000 |
| firmware_tampering/naive | 27 | 0.013 | 0.000 | 1.000 | 0.033 | 0.028 | 0.000 |
| firmware_tampering/stealthy | 27 | 0.011 | 0.000 | 0.928 | 0.035 | 0.039 | 0.000 |
| message_tampering/moderate | 27 | 0.236 | 0.000 | 0.000 | 0.032 | 0.033 | 0.260 |
| message_tampering/naive | 27 | 0.308 | 0.000 | 0.000 | 0.031 | 0.032 | 0.253 |
| message_tampering/stealthy | 27 | 0.100 | 0.000 | 0.000 | 0.033 | 0.033 | 0.270 |
| multi_stage/moderate | 27 | 0.009 | 0.166 | 0.000 | 0.267 | 0.034 | 0.240 |
| multi_stage/naive | 27 | 0.015 | 0.170 | 0.000 | 0.267 | 0.034 | 0.239 |
| multi_stage/stealthy | 27 | 0.007 | 0.206 | 0.000 | 0.158 | 0.040 | 0.240 |
| replay/moderate | 27 | 0.008 | 0.708 | 0.000 | 0.032 | 0.030 | 0.000 |
| replay/naive | 27 | 0.074 | 1.000 | 0.000 | 0.028 | 0.039 | 0.000 |
| replay/stealthy | 27 | 0.011 | 0.281 | 0.000 | 0.024 | 0.035 | 0.000 |
| sensor_spoof/moderate | 27 | 0.013 | 0.000 | 0.000 | 0.352 | 0.350 | 0.000 |
| sensor_spoof/naive | 27 | 0.011 | 0.000 | 0.000 | 0.363 | 0.359 | 0.000 |
| sensor_spoof/stealthy | 27 | 0.013 | 0.000 | 0.000 | 0.209 | 0.340 | 0.000 |

No feature perfectly separates the pooled attack runs from normal and fault runs: the run-level audit found no global single-feature separator. Some group-level telemetry is intentionally strong: naive replay has sequence anomalies in essentially every active tick, but normal/fault ranges still overlap on other behaviors and the signal does not establish intent.
