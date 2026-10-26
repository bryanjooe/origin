import pytest

from app.attack_injection import Attack, AttackType, StealthLevel
from app.detection import FeatureExtractor
from app.localization import LocalizationFeatureExtractor
from app.simulator import GridConfig, MicrogridSimulator


def energy_balance(row, config):
    dt = config.tick_seconds / 3600
    right = ((row["delivered_kw"] + row["excess_ac_kw"] + row["curtailed_dc_kw"]
              + row["inverter_loss_kw"]) * dt + row["battery_delta_kwh"]
             + row["battery_loss_kwh"])
    assert row["actual_solar_kw"] * dt == pytest.approx(right, abs=1e-10)
    assert row["delivered_kw"] + row["unmet_demand_kw"] == pytest.approx(row["demand_kw"])
    assert config.reserve_soc_pct - 1e-8 <= row["battery_soc_pct"] <= 100 + 1e-8
    assert 0 <= row["inverter_actual_kw"] <= config.inverter_limit_kw


def attack_run(kind, target, *, stealth="moderate", severity=0.8, seed=31):
    sim = MicrogridSimulator(GridConfig(start_hour=17), seed=seed)
    sim.inject_attack(kind, target, severity=severity, duration_ticks=12,
                      start_tick=2, stealth_level=stealth)
    rows = sim.run(18)
    return sim, rows


@pytest.mark.parametrize(("kind", "target"), [
    (AttackType.SENSOR_SPOOF, "solar_sensor"),
    (AttackType.REPLAY, "communication"),
    (AttackType.COMMUNICATION_DEGRADATION, "communication"),
    (AttackType.MESSAGE_TAMPERING, "communication"),
    (AttackType.CONTROLLER_COMPROMISE, "controller"),
    (AttackType.FIRMWARE_TAMPERING, "firmware"),
    (AttackType.ACTUATOR_ABUSE, "inverter"),
    (AttackType.MULTI_STAGE, "communication"),
])
def test_each_attack_produces_observable_telemetry_without_breaking_physics(kind, target):
    sim, rows = attack_run(kind, target)
    assert rows[:2] == MicrogridSimulator(GridConfig(start_hour=17), seed=31).run(2)
    assert all("security_telemetry" in row for row in rows)
    for row in rows:
        energy_balance(row, sim.config)
    assert len(sim.attacks.ground_truth()) == 1
    assert all("attack_type" not in row and "ground_truth" not in row for row in rows)


def test_sensor_spoof_is_observable_against_independent_redundant_measurement():
    _, rows = attack_run(AttackType.SENSOR_SPOOF, "solar_sensor", stealth="naive")
    attacked = rows[2]
    assert attacked["measured_solar_kw"] > attacked["redundant_solar_kw"] + 5
    assert attacked["security_telemetry"]["solar_sensors_agree"] is False
    # The physical solar production remains separate from the spoofed sensor reading.
    assert attacked["actual_solar_kw"] == attacked["expected_solar_kw"]


def test_battery_and_demand_sensor_spoofs_only_change_reported_values():
    battery_sim, battery_rows = attack_run(AttackType.SENSOR_SPOOF, "battery_sensor", stealth="naive")
    battery = battery_rows[2]
    assert abs(battery["measured_soc_pct"] - battery["redundant_soc_pct"]) > 20
    assert battery["security_telemetry"]["battery_sensors_agree"] is False

    demand_sim, demand_rows = attack_run(AttackType.SENSOR_SPOOF, "demand_sensor", stealth="naive")
    demand = demand_rows[2]
    assert demand["controller_inputs"]["demand_kw"] > demand["demand_kw"]
    assert demand["delivered_kw"] <= demand["demand_kw"]
    for sim, rows in ((battery_sim, battery_rows), (demand_sim, demand_rows)):
        for row in rows:
            energy_balance(row, sim.config)


def test_replay_repeats_sequence_and_communication_degradation_adds_latency():
    _, replay_rows = attack_run(AttackType.REPLAY, "communication")
    assert replay_rows[2]["security_telemetry"]["duplicate_sequence"] is True

    _, degraded_rows = attack_run(AttackType.COMMUNICATION_DEGRADATION, "communication", seed=7)
    assert max(row["communication_latency_seconds"] for row in degraded_rows[2:14]) > 60
    assert all(row["security_telemetry"]["auth_tag_validity"] in {"valid", "invalid", "missing"}
               for row in degraded_rows)


def test_tampering_controller_and_inverter_paths_sets_observable_indicators():
    _, controller_rows = attack_run(AttackType.MESSAGE_TAMPERING, "controller")
    assert controller_rows[2]["security_telemetry"]["command_policy_consistent"] is False
    _, inverter_rows = attack_run(AttackType.MESSAGE_TAMPERING, "inverter")
    assert inverter_rows[2]["inverter_requested_kw"] < inverter_rows[1]["inverter_requested_kw"]
    _, communication_rows = attack_run(AttackType.MESSAGE_TAMPERING, "communication")
    tags = [row["security_telemetry"]["auth_tag_validity"] for row in communication_rows[2:14]]
    assert "invalid" in tags
    assert "valid" in tags  # seeded imperfect tags avoid a deterministic attack fingerprint


def test_firmware_tampering_hash_mismatch_and_stealth_delay():
    _, ordinary = attack_run(AttackType.FIRMWARE_TAMPERING, "firmware", stealth="moderate")
    assert ordinary[2]["security_telemetry"]["config_integrity_match"] is False
    assert ordinary[2]["security_telemetry"]["config_hash"] != ordinary[2]["security_telemetry"]["last_known_good_config_hash"]

    _, stealthy = attack_run(AttackType.FIRMWARE_TAMPERING, "firmware", stealth="stealthy")
    assert stealthy[2]["config_integrity_ok"] is True
    assert stealthy[2]["security_telemetry"]["config_integrity_match"] is True
    assert stealthy[7]["config_integrity_ok"] is False
    assert stealthy[7]["security_telemetry"]["config_integrity_match"] is False


def test_multistage_attack_has_ordered_observable_phases():
    _, rows = attack_run(AttackType.MULTI_STAGE, "communication", stealth="moderate", severity=1.0)
    assert any(row["security_telemetry"]["duplicate_sequence"] for row in rows[2:6])
    assert rows[5]["security_telemetry"]["solar_sensors_agree"] is False
    assert rows[8]["security_telemetry"]["command_policy_consistent"] is False
    assert rows[11]["inverter_actual_kw"] < rows[11]["inverter_requested_kw"]


def test_attack_replay_is_seeded_and_ground_truth_stays_out_of_observations():
    first_sim, first = attack_run(AttackType.MULTI_STAGE, "communication", stealth="stealthy")
    second_sim, second = attack_run(AttackType.MULTI_STAGE, "communication", stealth="stealthy")
    assert first == second
    assert first_sim.attacks.ground_truth() == second_sim.attacks.ground_truth()
    for row in first:
        assert not {"attack", "attack_type", "stealth_level", "ground_truth"}.intersection(row)
        assert not {"attack", "attack_type", "stealth_level", "ground_truth"}.intersection(row["security_telemetry"])
    anomaly_observation = FeatureExtractor(first_sim.config).transform(first)
    source_observation = LocalizationFeatureExtractor(first_sim.config).transform(first)
    assert len(anomaly_observation) == len(source_observation) == len(first)
    assert all("attack" not in feature for item in anomaly_observation for feature in item.features)
    assert all("attack" not in feature for item in source_observation for feature in item.features)


def test_attack_schedule_validation_and_correction():
    sim = MicrogridSimulator()
    sim.inject_attack("sensor_spoof", "solar_sensor", start_tick=2, duration_ticks=3)
    sim.run(1)
    sim.inject_attack("actuator_abuse", "inverter", start_tick=5, duration_ticks=2)
    with pytest.raises(ValueError, match="Overlapping"):
        sim.inject_attack("replay", "communication", start_tick=4, duration_ticks=2)
    with pytest.raises(ValueError, match="past"):
        sim.inject_attack("replay", "communication", start_tick=0)
    with pytest.raises(ValueError, match="not valid"):
        Attack(AttackType.REPLAY, "controller", 0)
    sim.run(1)
    sim.correct()
    assert sim.attacks.at(sim.tick) is None
    assert sim.attacks.ground_truth()[0]["cancelled_at_tick"] == 2
