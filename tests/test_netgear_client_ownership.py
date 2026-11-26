from collections import Counter
import csv
from dataclasses import replace
from pathlib import Path

import pytest

from open_omada_device_agent import config
from open_omada_device_agent.adapters.outbound.netgear.adapter import NetgearAdapter
from open_omada_device_agent.adapters.outbound.netgear.platform import LazyNetgearAdapter, NetgearClientSource
from open_omada_device_agent.adapters.outbound.netgear.soap import AttachedClient, BandState
from open_omada_device_agent.bootstrap import runtime
from open_omada_device_agent.bootstrap.settings import AgentSettings
from open_omada_device_agent.util.mac_format import unicast_mac


AP_ONE = "02:00:00:00:a0:01"
AP_TWO = "02:00:00:00:a0:02"
PHONE = "da:00:00:00:00:01"


def station(mac=PHONE, *, ap=AP_ONE, band="5G", ssid="ExampleNet", connection="wireless"):
    return AttachedClient("", "Phone", mac, connection, None, None, band=band, ssid=ssid, reported_ap_mac=ap)


class Router:
    def __init__(self, rows):
        self.rows = rows
        self.polls = 0

    def login(self):
        pass

    def attached_clients_detailed(self):
        self.polls += 1
        if self.rows is None:
            raise OSError("SOAP unavailable")
        return self.rows

    def attached_clients(self):
        raise OSError("SOAP unavailable")

    def band_state(self, band):
        return BandState(band, "ExampleNet", True, True, "Auto", "", "", AP_ONE)


@pytest.mark.parametrize("configured", [AP_ONE.upper(), "02-00-00-00-A0-01", "02000000a001", "0200.0000.a001"])
def test_normalizes_physical_address(configured):
    assert unicast_mac(configured) == AP_ONE
    src = NetgearClientSource(NetgearAdapter(Router([station()])), physical_mac=configured)
    assert [s.mac for s in src()] == [PHONE]


@pytest.mark.parametrize("invalid", ["", "bad", "zz02:00:00:00:A0:01", "02:00-00-00:a0:01",
                                     "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF", "01:00:5E:00:00:01"])
def test_invalid_explicit_identity_refused_before_io(invalid):
    settings = replace(AgentSettings.from_environment(), controller_host="controller.example",
                       netgear_physical_mac=invalid)
    with pytest.raises(RuntimeError, match="OMADA_NETGEAR_PHYSICAL_MAC"):
        settings.validate()
    with pytest.raises(ValueError, match="OMADA_NETGEAR_PHYSICAL_MAC"):
        NetgearClientSource(NetgearAdapter(Router([])), physical_mac=invalid)


@pytest.mark.parametrize("report", [station(ap=AP_TWO), station(ap=None, connection="wired")])
@pytest.mark.parametrize("departed_first", [False, True])
def test_positive_departure_wins_even_in_conflicting_poll(report, departed_first):
    router = Router([station()])
    source = NetgearClientSource(NetgearAdapter(router), physical_mac=AP_ONE)
    assert [s.mac for s in source()] == [PHONE]
    report = replace(report, mac=PHONE.upper().replace(":", "-"))
    router.rows = [report, station()] if departed_first else [station(), report]
    assert source() == ()
    router.rows = [station(ap=None)]
    assert source() == ()


def test_missing_or_invalid_owner_never_establishes_or_renews_lease():
    clock = [100.0]
    router = Router([station(ap=None)])
    source = NetgearClientSource(NetgearAdapter(router), physical_mac=AP_ONE, now=lambda: clock[0])
    assert source() == ()
    router.rows = [station()]
    assert [s.mac for s in source()] == [PHONE]
    clock[0] += 100
    router.rows = [station(ap="00:00:00:00:00:00"), station(ap="zz02:00:00:00:A0:01"),
                   station(ap=AP_ONE, connection="unknown")]
    assert [s.mac for s in source()] == [PHONE]
    clock[0] += 201
    assert source() == ()


def test_cached_and_failed_polls_do_not_extend_strict_lease():
    clock = [1000.0]
    router = Router([station()])
    adapter = LazyNetgearAdapter(router, client_ttl_s=180, stale_ttl_s=600, now=lambda: clock[0])
    src = NetgearClientSource(adapter, physical_mac=AP_ONE, now=lambda: clock[0])
    assert [s.mac for s in src()] == [PHONE]
    router.rows = None
    clock[0] += 150
    assert [s.mac for s in src()] == [PHONE] and router.polls == 1
    clock[0] += 140
    assert [s.mac for s in src()] == [PHONE] and router.polls == 2
    clock[0] += 11
    assert src() == ()
    clock[0] += 301
    assert src() == ()
    router.rows = [station(ap=AP_TWO)]
    assert src() == ()
    router.rows = [station()]
    clock[0] += 181
    assert [s.mac for s in src()] == [PHONE]


def test_unconfigured_single_band_device_retains_legacy_associations():
    router = Router([station(ap=None, band="", ssid="")])
    assert NetgearClientSource(NetgearAdapter(router), physical_mac=AP_ONE, bands=("2.4G",))() == ()
    [client] = NetgearClientSource(NetgearAdapter(router), bands=("2.4G",))()
    assert client.mac == PHONE and client.ssid == "ExampleNet" and client.radio.value == "2g"


def test_runtime_station_radio_and_ssid_share_one_owned_observation(monkeypatch):
    router = Router([station(), station(mac="DA:00:00:00:00:02", band="6G", ssid="Guest"),
                     station(mac="DA:00:00:00:00:03", band="2.4G", ap=AP_TWO),
                     station(mac="DA:00:00:00:00:04", ap=None)])
    monkeypatch.setattr(config, "NETGEAR_PHYSICAL_MAC", AP_ONE)
    monkeypatch.setattr(runtime, "NetgearSoapClient", lambda *_args: router)
    s = replace(AgentSettings.from_environment(), southbound="netgear", model="EAP783", netgear_host="router.example",
                controller_host="controller.example", netgear_password="test", netgear_client_ttl=0,
                netgear_stale_ttl=0, device_ip="192.0.2.1")
    assert s.netgear_physical_mac == AP_ONE
    agent = runtime.build_runtime(s)
    first = agent.inform.build(need_reply=True, uptime=30)
    assert router.polls == 1
    assert {x["mac"] for x in first["clients"]} == {"DA-00-00-00-00-01", "DA-00-00-00-00-02"}
    assert [first["wSettings_" + x]["staNum"] for x in ("2G", "5G", "6G")] == [0, 1, 1]
    assert [first["ssidStats_" + x][0]["clntNum"] for x in ("2G", "5G", "6G")] == [0, 1, 0]
    router.rows = [station(ap=AP_TWO), station(mac="DA:00:00:00:00:02", ap=None, connection="wired")]
    second = agent.inform.build(need_reply=True, uptime=31)
    assert router.polls == 2 and second.get("clients", []) == []
    assert all(second["wSettings_" + x]["staNum"] == 0 and second["ssidStats_" + x][0]["clntNum"] == 0
               for x in ("2G", "5G", "6G"))

def test_replay_anonymized_simultaneous_two_ap_capture():
    path = Path(__file__).parent / "fixtures/netgear/paired_associations.csv"
    with path.open(newline="") as source:
        capture = list(csv.DictReader(source))
    rows = [station(row["station"], ap=row["reported_ap"], connection=row["connection"], band=row["band"])
            for row in capture]
    source_aps = ("02:00:00:00:a0:01", "02:00:00:00:a0:02")
    [wired] = [row for row in capture if row["connection"] == "wired"]
    assert wired["source_ap"] == wired["reported_ap"] == source_aps[0]
    expected_counts = ({"2g": 11, "5g": 3, "6g": 2}, {"2g": 34, "5g": 3})
    observed_devices = set()
    for physical, counts in zip(source_aps, expected_counts, strict=True):
        # Replay both sources together to exercise roaming attribution even
        # though this simultaneous sample itself had no duplicate clients.
        observed = NetgearClientSource(NetgearAdapter(Router(rows)), physical_mac=physical)()
        macs = {client.mac for client in observed}
        assert macs == {row["station"] for row in capture
                        if row["source_ap"] == physical and row["connection"] == "wireless"}
        assert Counter(client.radio.value for client in observed) == counts
        assert wired["station"] not in macs and macs.isdisjoint(observed_devices)
        observed_devices.update(macs)
