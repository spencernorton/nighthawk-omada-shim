import json

import pytest

from open_omada_device_agent.adapters.outbound.netgear.beacons import (
    MAX_AGE_SECONDS, ObservedRadioInform, primary_channel,
)


@pytest.mark.parametrize(("band", "frequency", "channel"), [
    ("2G", 2412, 1), ("2G", 2484, 14), ("5G", 5500, 100), ("6G", 6295, 69),
    ("6G", 5935, 2), ("6G", 7115, 233), ("5G", 6295, None),
    ("2G", 2413, None), ("6G", None, None), ("2G", True, None),
])
def test_primary_channel(band, frequency, channel):
    assert primary_channel(band, frequency) == channel


def test_observations_are_exact_and_expire_without_refreshing_cached_payload(tmp_path):
    path = tmp_path / "sample.json"
    now = [1000.]
    original = {
        "wSettings_5G": {"ch": "0", "busyUti": 0, "rxUti": 0, "txUti": 0, "interUti": 0},
        "ssidStats_5G": [{"ssid": "Home", "bssid": "02-11-22-33-44-55"}],
    }
    inform = ObservedRadioInform(lambda: original, path, now=lambda: now[0])
    record = {"observed_at": 1000., "frequency_mhz": 5500, "utilization_255": 128}
    def save(records):
        path.write_text(json.dumps({"version": 1, "radios": records}))
    assert inform() == original
    save({"02:11:22:33:44:66": record})
    assert inform() == original
    for bad in ({"observed_at": True}, {"observed_at": 1001}, {"frequency_mhz": 6295}):
        save({"02:11:22:33:44:55": {**record, **bad}})
        assert inform() == original
    save({"02:11:22:33:44:55": record})
    assert inform()["wSettings_5G"] == {"ch": "100", "busyUti": 50}
    original["wSettings_6G"] = {"ch": "0", "busyUti": 0, "txUti": 0, "rxUti": 0, "interUti": 0}
    assert inform()["wSettings_5G"]["interUti"] == 0
    assert inform()["wSettings_5G"]["busyUti"] == 50
    save({"02:11:22:33:44:55": {**record, "observed_at": 999, "frequency_mhz": 5200}})
    assert inform()["wSettings_5G"]["ch"] == "100"
    save({})
    assert inform()["wSettings_5G"]["ch"] == "100"
    assert original["wSettings_5G"]["ch"] == "0"
    original["wSettings_5G"]["ch"] = "40"
    assert inform() == original
    original["wSettings_5G"]["ch"] = "0"
    now[0] += MAX_AGE_SECONDS + 1
    assert inform() == original


@pytest.mark.parametrize("text", ["{", "null", '{"version":true,"radios":{}}', "x" * 17000])
def test_bad_document_preserves_other_telemetry(tmp_path, text):
    path = tmp_path / "sample.json"
    path.write_text(text)
    baseline = {"wSettings_5G": {"ch": "0"}}
    assert ObservedRadioInform(lambda: baseline, path)() == baseline


def test_independent_receivers_keep_the_newest_channel_and_matching_load(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    mac = "02:11:22:33:44:55"
    baseline = {"wSettings_5G": {"ch": "0", "rxUti": 0},
                "ssidStats_5G": [{"bssid": mac.upper()}]}
    now = [1000]
    inform = ObservedRadioInform(lambda: baseline, first, second, now=lambda: now[0])

    def publish(path, time, frequency, load=None):
        event = {"observed_at": time, "frequency_mhz": frequency}
        if load is not None:
            event["utilization_255"] = load
        path.write_text(json.dumps({"version": 1, "radios": {mac: event}}))

    publish(second, 995, 5500, 51)
    first.write_text("{")
    assert inform()["wSettings_5G"] == {"ch": "100", "busyUti": 20}
    publish(first, 998, 5500)
    assert inform()["wSettings_5G"] == {"ch": "100", "busyUti": 20}
    publish(first, 999, 5200)
    assert inform()["wSettings_5G"] == {"ch": "40", "rxUti": 0}
    publish(first, 1000, 5500)
    assert inform()["wSettings_5G"] == {"ch": "100", "rxUti": 0}
    publish(second, 1000, 5500, 102)
    assert inform()["wSettings_5G"] == {"ch": "100", "busyUti": 40}
    now[0] += MAX_AGE_SECONDS + 1
    assert inform() == baseline


def test_disagreement_at_the_same_time_does_not_choose_a_channel(tmp_path):
    paths = [tmp_path / name for name in ("first.json", "second.json")]
    mac = "02:00:00:00:a0:9f"
    baseline = {"wSettings_5G": {"ch": "0", "rxUti": 0}, "ssidStats_5G": [{"bssid": mac}]}
    for path, frequency in zip(paths, (5500, 5200), strict=True):
        entry = {"observed_at": 1000, "frequency_mhz": frequency, "utilization_255": 51}
        path.write_text(json.dumps({"version": 1, "radios": {mac: entry}}))
    for order in (paths, list(reversed(paths))):
        inform = ObservedRadioInform(lambda: baseline, *order, now=lambda: 1010)
        assert inform() == baseline


def test_dashboard_primary_survives_gaps_and_rejects_airtime_from_another_channel(tmp_path):
    path = tmp_path / "receiver"
    mac = "02:11:22:33:44:55"
    base = {"wSettings_5G": {"ch": "0", "rxUti": 0}, "ssidStats_5G": [{"bssid": mac}]}
    panel = {"5G": 40}
    source = ObservedRadioInform(lambda: base, path, now=lambda: 1000, panel_channels=lambda: panel)
    assert source()["wSettings_5G"] == {"ch": "40", "rxUti": 0}
    entry = {"observed_at": 990, "frequency_mhz": 5500, "utilization_255": 51}
    path.write_text(json.dumps({"version": 1, "radios": {mac: entry}}))
    assert source()["wSettings_5G"] == {"ch": "40", "rxUti": 0}
    entry.update(frequency_mhz=5200, observed_at=995, utilization_255=102)
    path.write_text(json.dumps({"version": 1, "radios": {mac: entry}}))
    assert source()["wSettings_5G"] == {"ch": "40", "busyUti": 40}
    panel["5G"] = 100
    assert source()["wSettings_5G"] == {"ch": "100", "rxUti": 0}
    panel.clear()
    assert source()["wSettings_5G"] == {"ch": "0", "rxUti": 0}
    assert base["wSettings_5G"] == {"ch": "0", "rxUti": 0}


def test_dashboard_round_trip_while_receiver_absent_cannot_resurrect_old_airtime(tmp_path):
    path = tmp_path / "radio.json"
    mac = "02:11:22:33:44:55"
    payload = {"wSettings_5G":{"ch":"0"}, "ssidStats_5G":[{"bssid":mac}]}
    now = [1000.]
    panel = {"5G":100}
    source = ObservedRadioInform(lambda:payload, path, now=lambda:now[0], panel_channels=lambda:panel)
    def publish(stamp, utilization):
        entry = {"observed_at":stamp, "frequency_mhz":5500, "utilization_255":utilization}
        path.write_text(json.dumps({"version":1, "radios":{mac:entry}}))
    publish(990., 51)
    assert source()["wSettings_5G"] == {"ch":"100", "busyUti":20}
    path.unlink()
    now[0] = 1001.
    panel["5G"] = 40
    assert source()["wSettings_5G"] == {"ch":"40"}
    now[0] = 1002.
    panel["5G"] = 100
    assert source()["wSettings_5G"] == {"ch":"100"}
    path.write_text('{"version":1,"radios":{}}')
    assert source()["wSettings_5G"] == {"ch":"100"}
    publish(990., 51)
    assert source()["wSettings_5G"] == {"ch":"100"}
    now[0] = 1010.
    publish(1003., 102)
    assert source()["wSettings_5G"] == {"ch":"100","busyUti":40}


def test_new_fixed_soap_configuration_wins_over_older_panel_channel(tmp_path):
    now = [1000.]
    mac = "02:11:22:33:44:55"
    base = {"wSettings_5G":{"ch":"0"}, "ssidStats_5G":[{"bssid":mac}]}
    path = tmp_path / "receiver"
    def publish(timestamp, frequency, load):
        path.write_text(json.dumps({"version":1,"radios":{mac:{
            "observed_at":timestamp, "frequency_mhz":frequency, "utilization_255":load}}}))
    source = ObservedRadioInform(lambda:base, path, now=lambda:now[0], panel_channels=lambda:{"5G":100})
    publish(990, 5500, 102)
    assert source()["wSettings_5G"] == {"ch":"100","busyUti":40}
    now[0] = 1002.
    base["wSettings_5G"]["ch"] = "40"
    assert source()["wSettings_5G"] == {"ch":"40"}
    now[0] = 1010.
    publish(1005, 5200, 51)
    assert source()["wSettings_5G"] == {"ch":"40","busyUti":20}
