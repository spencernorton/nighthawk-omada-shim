import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_omada_device_agent.adapters.outbound.netgear.uplink import ObservedUplink
from open_omada_device_agent.projections.inform import InformAssembler, LanObservation


script = Path(__file__).resolve().parents[1] / "scripts" / "observe-omada-uplink.py"
spec = importlib.util.spec_from_file_location("uplink_observer", script)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

args = SimpleNamespace(ap_mac="AA-11-22-33-44-55", ap_ip="192.0.2.22",
                       switch_mac="FE-ED-10-20-DD-CC", port=3)


def sources():
    return (
        {"mac": args.ap_mac, "ip": args.ap_ip, "active": True, "wireless": False,
         "switchMac": args.switch_mac, "port": args.port, "lastSeen": 1000000},
        {"mac": args.switch_mac, "status": 14, "lastSeen": 1000000,
         "ports": [{"port": 3, "disable": False,
                    "portStatus": {"port": 3, "linkStatus": 1, "rx": 10000, "tx": 80000}}]},
    )


@pytest.mark.parametrize("client_delta,switch_delta", [
    ({"switchMac": "00-11-22-33-44-55"}, {}), ({"port": 1}, {}),
    ({"active": False}, {}), ({"wireless": True}, {}), ({"lastSeen": 100}, {}),
    ({}, {"status": 10}), ({}, {"lastSeen": 900}), ({}, {"ports": []}),
])
def test_collector_rejects_unqualified_attachment(client_delta, switch_delta):
    client, switch = sources()
    with pytest.raises(collector.UnqualifiedObservation):
        collector.observation(client | client_delta, switch | switch_delta, args, 1000)


def test_collector_rejects_down_port_and_invalid_counters():
    client, switch = sources()
    status = switch["ports"][0]["portStatus"]
    for update in ({"linkStatus": 0}, {"rx": True}, {"tx": -1}):
        original = status.copy()
        status.update(update)
        with pytest.raises(collector.UnqualifiedObservation):
            collector.observation(client, switch, args, 1000)
        status.update(original)


def test_informs_use_new_switch_observations_in_the_ap_direction(tmp_path):
    path = tmp_path / "uplink.json"
    doc = collector.observation(*sources(), args, 1000)
    clock = [1000]
    reader = ObservedUplink(path, args.ap_ip, now=lambda: clock[0])
    inform = InformAssembler(device_info=lambda: {}, lan=LanObservation(10000.0, 1, "LAN"),
                             clients=lambda: (), client_projection=lambda _: [],
                             wireless_projection=lambda: {}, uplink_traffic=reader)

    def report(uptime):
        path.write_text(json.dumps(doc))
        return inform.build(need_reply=True, uptime=uptime).get("lanTraffic")

    assert report(800) == {"port": "LAN"}
    assert report(801) is None  # same switch observation
    doc.update(observed_at_ms=1030000, switch_rx_bytes=12000, switch_tx_bytes=85000)
    clock[0] = 1031
    assert report(831) == {"port": "LAN", "rx": 85000, "tx": 12000}
    clock[0] = 1040
    doc.update(observed_at_ms=1010000)
    assert report(840) is None  # out of order
    clock[0] = 1060
    doc.update(observed_at_ms=1060000, switch_tx_bytes=1)
    assert report(860) == {"port": "LAN"}  # switch counters reset
    clock[0] = 1090
    doc.update(observed_at_ms=1090000, switch_tx_bytes=8)
    assert report(10) == {"port": "LAN"}  # AP rebooted independently
    clock[0] = 1120
    doc.update(observed_at_ms=1120000, switch_tx_bytes=24000)
    assert report(40) == {"port": "LAN", "rx": 24000, "tx": 12000}
    clock[0] = 1240
    assert report(160) == {"port": "LAN"}  # clear the retained rate on expiry
    assert report(170) is None


@pytest.mark.parametrize("change", [
    {"ap_ip": "192.0.2.23"}, {"observed_at_ms": 3000000}, {"observed_at_ms": 10**350}, {"switch_rx_bytes": -1},
    {"switch_tx_bytes": 2**63}, {"version": True}, {"ap_mac": "other"}, {"port": False},
])
def test_unusable_sampler_file_keeps_normal_informs(tmp_path, change):
    path = tmp_path / "sample"
    reader = ObservedUplink(path, args.ap_ip, now=lambda: 1000)
    doc = collector.observation(*sources(), args, 1000)
    assert reader("LAN", "0 days 01:02:03") == {"port": "LAN"}  # clear on startup
    for text in ("[", json.dumps([doc]), json.dumps(doc | change), " " * 4100):
        path.write_text(text)
        assert reader("LAN", "0 days 01:02:03") is None
