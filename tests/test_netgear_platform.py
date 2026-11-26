"""Tests for the Netgear platform port and poll-merged client source."""
from open_omada_device_agent.adapters.outbound.netgear.adapter import (
    DesiredMainWlan,
    NetgearReconcileResult,
    netgear_capabilities,
)
from open_omada_device_agent.adapters.outbound.netgear.platform import (
    NetgearClientSource,
    NetgearPlatformPort,
)
from open_omada_device_agent.adapters.outbound.netgear.soap import (
    AttachedClient,
    BandState,
)
from open_omada_device_agent.application.commands import ApplyDeviceConfigurationCommand
from open_omada_device_agent.contexts.wireless.domain import (
    CaptivePortalIntent,
    RadioBand,
    RadioConfig,
    WirelessNetwork,
    WirelessSecurity,
    WirelessVlanIntent,
)
from open_omada_device_agent.shared.domain import SecretValue


def _wlan(name="ExampleNet", psk=None, vlan_id=None, band=RadioBand.TWO_G):
    return WirelessNetwork(
        band=band, radio_id=0, ssid_id=1, index=0, operation=1,
        name=name, broadcast=True, client_isolation=False,
        vlan=WirelessVlanIntent(vlan_id=vlan_id),
        security=WirelessSecurity(psk_key=SecretValue(psk) if psk else None),
        portal=CaptivePortalIntent(),
    )


def _cmd(**kw):
    base = dict(sequence_id=1, config_version=1, config_version_inc=None)
    base.update(kw)
    return ApplyDeviceConfigurationCommand(**base)


class FakeAdapter:
    def __init__(self):
        self.desired = None
        self.clients = []
        self.state = {b: BandState(band=b, ssid="ExampleNet", enabled=True,
                                    broadcast=True, channel="01", wireless_mode="",
                                    security="", mac="")
                      for b in ("2.4G", "5G", "6G")}

    def reconcile(self, desired: DesiredMainWlan):
        self.desired = desired
        return NetgearReconcileResult(applied=True, changed=True, calls=3)

    def read_clients(self):
        return list(self.clients)

    def read_state(self):
        return dict(self.state)


def test_reconcile_single_ssid_maps_psk_and_channels():
    fake = FakeAdapter()
    port = NetgearPlatformPort(fake)
    result = port.reconcile(_cmd(
        wlans=(_wlan(psk="secret123"),),
        radios=(RadioConfig(band=RadioBand.TWO_G, channel=6),),
    ), netgear_capabilities())
    assert result.applied and result.changed
    assert fake.desired.ssid == "ExampleNet"
    assert fake.desired.passphrase == "secret123"
    assert fake.desired.channels == (("2.4G", "6"),)


def test_reconcile_rejects_second_ssid():
    port = NetgearPlatformPort(FakeAdapter())
    result = port.reconcile(_cmd(wlans=(_wlan("One"), _wlan("Two"))),
                            netgear_capabilities())
    assert not result.applied and "one main SSID" in result.error


def test_reconcile_rejects_vlan_tagged_ssid():
    port = NetgearPlatformPort(FakeAdapter())
    result = port.reconcile(_cmd(wlans=(_wlan(vlan_id=20),)),
                            netgear_capabilities())
    assert not result.applied and "vlan" in result.error


def test_wireless_inform_reports_wsettings_from_bands():
    from open_omada_device_agent.adapters.outbound.netgear.platform import NetgearWirelessInform
    from open_omada_device_agent.adapters.outbound.netgear.adapter import (
        BandState, NetgearAdapter)

    bands = {
        "2.4G": BandState(band="2.4G", ssid="HomeBase", enabled=True, broadcast=True,
                          channel="Auto", wireless_mode="m", security="WPA2", mac="74:00:00:00:00:01"),
        "5G": BandState(band="5G", ssid="HomeBase", enabled=True, broadcast=True,
                        channel="157", wireless_mode="m", security="WPA2", mac="74:00:00:00:00:02"),
        "6G": BandState(band="6G", ssid="HomeBase", enabled=True, broadcast=True,
                        channel="69", wireless_mode="m", security="WPA3", mac="74:00:00:00:00:03"),
    }

    class C:
        def login(self): pass
        def band_state(self, band): return bands[band]
        def attached_clients(self): return []
    payload = NetgearWirelessInform(NetgearAdapter(C()))()
    assert payload["wSettings_2G"]["ch"] == "0"
    assert payload["wSettings_5G"]["ch"] == "157"
    assert "ssidStats" not in payload["wSettings_6G"]
    assert payload["ssidStats_6G"][0]["ssid"] == "HomeBase"
    assert payload["ssidStats_6G"][0]["bssid"] == "74-00-00-00-00-03"
    assert payload["ssidStats_6G"][0]["clntNum"] == 0


def test_wireless_inform_counts_clients_per_band_when_known():
    from open_omada_device_agent.adapters.outbound.netgear.platform import NetgearWirelessInform
    from open_omada_device_agent.adapters.outbound.netgear.adapter import (
        BandState, NetgearAdapter)
    from open_omada_device_agent.adapters.outbound.netgear.soap import AttachedClient

    bands = {b: BandState(band=b, ssid="HomeBase", enabled=True, broadcast=True,
                          channel="01", wireless_mode="m", security="WPA2",
                          mac=f"74:00:00:00:00:0{i}")
             for i, b in enumerate(("2.4G", "5G", "6G"), start=1)}

    class C:
        def login(self): pass
        def band_state(self, band): return bands[band]
        def attached_clients(self): raise AssertionError("v1 must not be used")
        def attached_clients_detailed(self):
            return [
                AttachedClient("192.0.2.1", "A", "AA:BB:CC:DD:EE:01", "wireless", 100, 50, band="2.4G", ssid="HomeBase"),
                AttachedClient("192.0.2.2", "B", "AA:BB:CC:DD:EE:02", "wireless", 100, 50, band="2.4G", ssid="OtherIoT"),
                AttachedClient("192.0.2.3", "C", "AA:BB:CC:DD:EE:03", "wireless", 100, 50, band="6G", ssid="HomeBase"),
                AttachedClient("192.0.2.4", "D", "AA:BB:CC:DD:EE:04", "wired", 1000, None, band="2.4G", ssid="HomeBase"),
                AttachedClient("192.0.2.5", "E", "AA:BB:CC:DD:EE:05", "wireless", 100, 50, band="5G", ssid=""),
            ]

    payload = NetgearWirelessInform(NetgearAdapter(C()))()
    assert payload["ssidStats_2G"][0]["clntNum"] == 1  # IoT and wired excluded
    assert payload["wSettings_2G"]["staNum"] == 2
    assert payload["ssidStats_5G"][0]["clntNum"] == 0  # unknown SSID is not main-SSID attribution
    assert payload["ssidStats_6G"][0]["clntNum"] == 1


def test_attach_device_v1_fallback_restores_only_single_band_attribution():
    from open_omada_device_agent.adapters.outbound.netgear.adapter import NetgearAdapter
    from open_omada_device_agent.adapters.outbound.netgear.platform import (
        NetgearWirelessInform,
    )
    from open_omada_device_agent.contexts.clients.domain import ClientRadioBand

    bands = {
        band: BandState(
            band=band,
            ssid="HomeBase",
            enabled=True,
            broadcast=True,
            channel="01",
            wireless_mode="m",
            security="WPA2",
            mac=f"74:00:00:00:00:0{index}",
        )
        for index, band in enumerate(("2.4G", "5G", "6G"), start=1)
    }

    class LegacyClient:
        def __init__(self):
            self.calls = []

        def band_state(self, band):
            return bands[band]

        def attached_clients_detailed(self):
            self.calls.append("v2")
            raise RuntimeError("GetAttachDevice2 unavailable")

        def attached_clients(self):
            self.calls.append("v1")
            return [
                AttachedClient(
                    "192.0.2.10", "LegacyWifi", "AA:BB:CC:DD:EE:10",
                    "wireless", 144, 80,
                ),
                AttachedClient(
                    "192.0.2.11", "Server", "AA:BB:CC:DD:EE:11",
                    "wired", 1000, None,
                ),
                AttachedClient(
                    "192.0.2.12", "Unknown", "AA:BB:CC:DD:EE:12",
                    "unknown", None, None,
                ),
            ]

    client = LegacyClient()
    adapter = NetgearAdapter(client)
    assert [c.name for c in adapter.read_clients()] == [
        "LegacyWifi", "Server", "Unknown",
    ]
    assert client.calls == ["v2", "v1"]

    single_band_payload = NetgearWirelessInform(adapter, bands=("2.4G",))()
    assert single_band_payload["wSettings_2G"]["staNum"] == 1
    assert single_band_payload["ssidStats_2G"][0]["clntNum"] == 1
    single_band_clients = NetgearClientSource(adapter, bands=("2.4G",))()
    assert len(single_band_clients) == 1
    assert single_band_clients[0].hostname == "LegacyWifi"
    assert single_band_clients[0].ssid == "HomeBase"
    assert single_band_clients[0].radio is ClientRadioBand.TWO_G

    tri_band_payload = NetgearWirelessInform(adapter)()
    assert all(
        tri_band_payload[f"wSettings_{suffix}"]["staNum"] == 0
        for suffix in ("2G", "5G", "6G")
    )
    assert all(
        tri_band_payload[f"ssidStats_{suffix}"][0]["clntNum"] == 0
        for suffix in ("2G", "5G", "6G")
    )
    assert NetgearClientSource(adapter)() == ()


def test_client_source_excludes_wired_and_unattributable_clients():
    from open_omada_device_agent.contexts.clients.domain import ClientRadioBand
    fake = FakeAdapter()
    clock = [1000.0]
    src = NetgearClientSource(fake, expire_s=300.0, now=lambda: clock[0])
    fake.clients = [
        AttachedClient(ip="192.0.2.5", name="Phone",
                       mac="AA:BB:CC:DD:EE:01", connection="wireless",
                       link_rate_mbps=2345, signal_percent=60, band="6G", ssid="ExampleNet"),
        AttachedClient(ip="192.0.2.7", name="LegacyWifi",
                       mac="AA:BB:CC:DD:EE:03", connection="wireless",
                       link_rate_mbps=144, signal_percent=80),  # v1 fallback (band="")
        AttachedClient(ip="192.0.2.6", name="Srv",
                       mac="AA:BB:CC:DD:EE:02", connection="wired",
                       link_rate_mbps=1000, signal_percent=None),
    ]
    first = src()
    # Wired and unknown-radio hosts must not enter EAP informs without a valid rid.
    assert len(first) == 1
    by_name = {c.hostname: c for c in first}
    assert "Srv" not in by_name and "LegacyWifi" not in by_name
    assert by_name["Phone"].wireless and by_name["Phone"].rssi == -70
    assert by_name["Phone"].radio is ClientRadioBand.SIX_G
    assert by_name["Phone"].rx_rate == 2345000 and by_name["Phone"].tx_rate == 2345000
    fake.clients = []  # Netgear churn: client missing from next poll
    clock[0] += 60
    assert len(src()) == 1  # retained by ageing
    # A wireless client that moves to Ethernet is immediately evicted from wireless informs
    fake.clients = [AttachedClient(ip="192.0.2.5", name="Phone",
                                   mac="AA:BB:CC:DD:EE:01", connection="wired",
                                   link_rate_mbps=1000, signal_percent=None)]
    assert src() == ()
    fake.clients = []
    clock[0] += 301
    assert src() == ()  # expired


def test_lazy_adapter_caches_client_polls_across_inform_sources():
    from open_omada_device_agent.adapters.outbound.netgear.platform import (
        LazyNetgearAdapter,
        NetgearWirelessInform,
    )

    clock = [100.0]
    calls = {"login": 0, "clients": 0}
    bands = {
        b: BandState(
            band=b, ssid="HomeBase", enabled=True, broadcast=True,
            channel="01", wireless_mode="m", security="WPA2",
            mac=f"74:00:00:00:00:0{i}",
        )
        for i, b in enumerate(("2.4G", "5G", "6G"), start=1)
    }

    class CountingClient:
        def login(self):
            calls["login"] += 1

        def band_state(self, band):
            return bands[band]

        def attached_clients_detailed(self):
            calls["clients"] += 1
            return [
                AttachedClient(
                    "192.0.2.10", "Laptop", "AA:BB:CC:DD:EE:10",
                    "wireless", 2400, 80, band="6G", ssid="HomeBase",
                )
            ]

    adapter = LazyNetgearAdapter(CountingClient(), client_ttl_s=30.0, now=lambda: clock[0])
    client_src = NetgearClientSource(adapter, now=lambda: clock[0])
    wireless_src = NetgearWirelessInform(adapter, ttl_s=60.0, now=lambda: clock[0])

    # Both inform projections share one GetAttachDevice2 SOAP read within the 30s TTL
    assert len(client_src()) == 1
    assert wireless_src()["ssidStats_6G"][0]["clntNum"] == 1
    clock[0] += 3.0
    assert len(client_src()) == 1
    assert calls == {"login": 1, "clients": 1}

    # Once TTL expires, the next inform refreshes from SOAP
    clock[0] += 28.0
    assert len(client_src()) == 1
    assert calls == {"login": 1, "clients": 2}




def test_lazy_adapter_serves_bounded_stale_cache_on_transient_soap_errors():
    import pytest
    from open_omada_device_agent.adapters.outbound.netgear.platform import LazyNetgearAdapter
    from open_omada_device_agent.adapters.outbound.netgear.soap import SoapError

    clock = [100.0]
    fail = [False]
    bands = {
        b: BandState(
            band=b, ssid="HomeBase", enabled=True, broadcast=True,
            channel="01", wireless_mode="688Mbps", security="WPA2",
            mac=f"74:00:00:00:00:0{i}",
        )
        for i, b in enumerate(("2.4G", "5G", "6G"), start=1)
    }

    class FlakyClient:
        def login(self):
            pass

        def attached_clients(self):
            if fail[0]:
                raise SoapError("transient timeout")
            return []

        def band_state(self, band):
            if fail[0]:
                raise SoapError("transient 500")
            return bands[band]

        def attached_clients_detailed(self):
            if fail[0]:
                raise SoapError("transient timeout")
            return [
                AttachedClient(
                    "192.0.2.10", "Laptop", "AA:BB:CC:DD:EE:10",
                    "wireless", 2400, 80, band="6G", ssid="HomeBase",
                )
            ]

        def sys_uptime_seconds(self):
            if fail[0]:
                raise SoapError("transient timeout")
            return 1000

    adapter = LazyNetgearAdapter(
        FlakyClient(), client_ttl_s=30.0, state_ttl_s=30.0, stale_ttl_s=180.0, now=lambda: clock[0]
    )
    assert adapter.read_state()["2.4G"].ssid == "HomeBase"
    assert len(adapter.read_clients()) == 1
    assert adapter.read_uptime() == 1000

    # Advance past fresh TTL (30s) into stale window (<180s) while router fails
    clock[0] += 45.0
    fail[0] = True
    assert adapter.read_state()["2.4G"].ssid == "HomeBase"
    assert len(adapter.read_clients()) == 1
    assert adapter.read_uptime() == 1045

    # Beyond stale_ttl_s (180s), read_state/read_clients surface the error and read_uptime returns None
    clock[0] += 150.0
    with pytest.raises(SoapError):
        adapter.read_state()
    with pytest.raises(SoapError):
        adapter.read_clients()
    assert adapter.read_uptime() is None


def test_lazy_adapter_caches_system_info_and_expires_stale_memory():
    from open_omada_device_agent.adapters.outbound.netgear.platform import LazyNetgearAdapter
    from open_omada_device_agent.adapters.outbound.netgear.soap import SoapError, SystemInfo

    clock = [100.0]
    fail = [False]
    calls = {"login": 0, "system_info": 0}

    class FlakyClient:
        def login(self):
            calls["login"] += 1

        def system_info(self):
            calls["system_info"] += 1
            if fail[0]:
                raise SoapError("transient timeout")
            return SystemInfo(load_average_x100=164, free_memory_percent=100)

    adapter = LazyNetgearAdapter(
        FlakyClient(), state_ttl_s=30.0, stale_ttl_s=60.0, now=lambda: clock[0]
    )

    assert adapter.read_system_info().load_average_x100 == 164
    assert adapter.read_used_memory_percent() == 0
    assert adapter.read_used_memory_percent() == 0
    assert calls == {"login": 1, "system_info": 1}

    clock[0] += 30.0
    fail[0] = True
    assert adapter.read_used_memory_percent() == 0
    assert calls["system_info"] == 2

    clock[0] += 60.0
    assert adapter.read_used_memory_percent() is None
    assert calls["system_info"] == 3


def test_wireless_inform_projects_omada_63_radio_scalars_and_ssid_id():
    from open_omada_device_agent.adapters.outbound.netgear.adapter import NetgearAdapter
    from open_omada_device_agent.adapters.outbound.netgear.platform import (
        NetgearPlatformPort,
        NetgearWirelessInform,
    )

    bands = {
        "2.4G": BandState(
            band="2.4G", ssid="ExampleNet", enabled=True, broadcast=True,
            channel="06", wireless_mode="688Mbps", security="WPA2", mac="02:00:00:00:A1:02",
        ),
        "5G": BandState(
            band="5G", ssid="ExampleNet", enabled=True, broadcast=True,
            channel="44", wireless_mode="5765Mbps", security="WPA2", mac="02:00:00:00:A1:03",
        ),
        "6G": BandState(
            band="6G", ssid="ExampleNet", enabled=True, broadcast=True,
            channel="69", wireless_mode="11529Mbps", security="WPA3", mac="02:00:00:00:A1:04",
        ),
    }

    class RouterStub:
        def login(self):
            pass

        def band_state(self, band):
            return bands[band]

        def current_psk(self, band):
            return "secret123"

        def attached_clients_detailed(self):
            return [
                AttachedClient("192.0.2.50", "Phone", "AA:BB:CC:DD:EE:01", "wireless", 1201, 75, band="5G", ssid="ExampleNet"),
                AttachedClient("192.0.2.51", "Plug", "AA:BB:CC:DD:EE:02", "wireless", 72, 60, band="2.4G", ssid="ExampleIoT"),
            ]

    ssid_ids: dict[tuple[str, str], int] = {}
    adapter = NetgearAdapter(RouterStub())
    port = NetgearPlatformPort(adapter, ssid_ids=ssid_ids)
    inform = NetgearWirelessInform(adapter, ssid_ids=ssid_ids)

    initial = inform()
    assert initial["wSettings_2G"] == {
        "ch": "6",
        "bw": "40MHz",
        "txPower": "25dBm",
        "txUti": 0,
        "rxUti": 0,
        "interUti": 0,
        "busyUti": 0,
        "staNum": 1,
        "rdMode": "11be",
        "txR": "688.0Mbps",
    }
    assert initial["wSettings_5G"]["txR"] == "5765.0Mbps"
    assert initial["wSettings_5G"]["bw"] == "160MHz"
    assert initial["wSettings_5G"]["staNum"] == 1
    assert initial["wSettings_6G"]["txR"] == "11529.0Mbps"
    assert initial["wSettings_6G"]["bw"] == "320MHz"
    assert initial["wSettings_6G"]["txPower"] == "23dBm"
    assert initial["ssidStats_2G"][0]["id"] == 0
    assert initial["ssidStats_2G"][0]["clntNum"] == 0  # Guest/IoT excluded from main SSID count
    assert initial["ssidStats_5G"][0]["clntNum"] == 1

    # Provisioning main WLAN via SET_REQUEST propagates ssid_id immediately
    wlan_5g = WirelessNetwork(
        band=RadioBand.FIVE_G,
        radio_id=1,
        ssid_id=42,
        index=0,
        operation=1,
        name="ExampleNet",
        broadcast=True,
        client_isolation=False,
        vlan=WirelessVlanIntent(),
        security=WirelessSecurity(psk_key=SecretValue("secret123")),
        portal=CaptivePortalIntent(),
    )
    res = port.reconcile(_cmd(wlans=(wlan_5g,)), netgear_capabilities())
    assert res.applied
    updated = inform()
    assert updated["ssidStats_5G"][0]["id"] == 42


def test_client_source_normalizes_identity_without_inventing_fields():
    from open_omada_device_agent.contexts.clients.domain import ClientRadioBand

    fake = FakeAdapter()
    clock = [1000.0]
    src = NetgearClientSource(fake, now=lambda: clock[0])
    fake.clients = [
        AttachedClient(
            ip="", name="", mac="aa-bb-cc-dd-ee-01", connection="wireless",
            link_rate_mbps=0, signal_percent=None, band="5G", ssid="",
        ),
        AttachedClient(
            ip="192.0.2.99", name="Bad", mac="not-a-mac", connection="wireless",
            link_rate_mbps=100, signal_percent=50, band="2.4G", ssid="ExampleNet",
        ),
    ]

    first = src()
    assert len(first) == 1
    client = first[0]
    assert client.mac == "aa:bb:cc:dd:ee:01"
    assert client.ipv4 is None and client.hostname is None and client.ssid is None
    assert client.radio is ClientRadioBand.FIVE_G
    assert client.rx_rate is None and client.tx_rate is None

    fake.clients = [
        AttachedClient(
            ip="192.0.2.5", name="Phone", mac="AA:BB:CC:DD:EE:01", connection="wireless",
            link_rate_mbps=1200, signal_percent=80, band="5G", ssid="ExampleNet",
        )
    ]
    clock[0] += 1
    second = src()
    assert len(second) == 1
    assert second[0].hostname == "Phone" and second[0].ssid == "ExampleNet"
    assert second[0].rx_rate == 1200000

    fake.clients = [
        AttachedClient(
            ip="192.0.2.5", name="Phone", mac="AABBCCDDEE01", connection="wired",
            link_rate_mbps=1000, signal_percent=None,
        )
    ]
    assert src() == ()


def test_wireless_inform_client_errors_use_only_bounded_stale_counts():
    from open_omada_device_agent.adapters.outbound.netgear.adapter import NetgearAdapter
    from open_omada_device_agent.adapters.outbound.netgear.platform import NetgearWirelessInform

    clock = [100.0]
    fail = [False]
    bands = {
        b: BandState(
            band=b, ssid="HomeBase", enabled=True, broadcast=True,
            channel="01", wireless_mode="688Mbps", security="WPA2",
            mac=f"74:00:00:00:00:0{i}",
        )
        for i, b in enumerate(("2.4G", "5G", "6G"), start=1)
    }

    class RouterStub:
        def band_state(self, band):
            return bands[band]

        def attached_clients_detailed(self):
            if fail[0]:
                raise RuntimeError("client poll failed")
            return [
                AttachedClient(
                    "192.0.2.10", "Laptop", "AA:BB:CC:DD:EE:10",
                    "wireless", 2400, 80, band="6G", ssid="HomeBase",
                )
            ]

        def attached_clients(self):
            raise RuntimeError("client poll failed")

    adapter = NetgearAdapter(RouterStub())
    inform = NetgearWirelessInform(
        adapter, ttl_s=60.0, stale_ttl_s=180.0, now=lambda: clock[0]
    )
    initial = inform()
    assert initial["ssidStats_6G"][0]["clntNum"] == 1

    fail[0] = True
    clock[0] += 61.0
    assert inform() == initial
    clock[0] += 120.0
    assert inform() == {}
    assert NetgearWirelessInform(
        adapter, ttl_s=60.0, stale_ttl_s=180.0, now=lambda: clock[0]
    )() == {}


def test_reconcile_accepts_bundled_supported_update_with_passive_portal_policy():
    from open_omada_device_agent.ap_config import parse_config_body

    fake = FakeAdapter()
    update = parse_config_body(
        {
            "wirelessBasic_2G": {
                "radioEnable": True,
                "chanWidth": 0,
                "channel": 6,
                "txPower": 0,
                "channelLimit": False,
                "wirelessMode": 0,
            },
            "ssid_2G": {
                "ssid": [
                    {
                        "operation": 1,
                        "ssidName": "ExampleNet",
                        "ssidBcast": True,
                        "ssidIsolation": False,
                        "securityMode": 3,
                        "pskVer": 3,
                        "pskCipher": 1,
                        "pskKey": "secret123",
                        "pmfMode": 0,
                        "fastTransition": {"enable11r": False},
                    }
                ]
            },
            "led": {"enable": "on", "locate": False},
            "wifiControlLed": {"enable": "on", "isPressed": False},
            "portalFreePolicyConfig": {
                "portalFreePolicy": [{"value": "192.0.2.1"}],
                "urlPortalFreePolicy": [{"host": "example.com"}],
            },
        }
    )

    result = NetgearPlatformPort(fake).reconcile(update, netgear_capabilities())

    assert result.applied is True
    assert result.error == ""
    assert fake.desired == DesiredMainWlan(
        ssid="ExampleNet",
        passphrase="secret123",
        channels=(("2.4G", "6"),),
    )


def test_reconcile_rejects_actionable_radio_settings_without_router_writes():
    cases = (
        (RadioConfig(RadioBand.TWO_G, enabled=False), "radioEnable=False"),
        (RadioConfig(RadioBand.TWO_G, channel_width=20), "chanWidth=20"),
        (RadioConfig(RadioBand.TWO_G, tx_power=18), "txPower=18"),
        (RadioConfig(RadioBand.TWO_G, channel_limit=True), "channelLimit=True"),
        (RadioConfig(RadioBand.TWO_G, wireless_mode=1), "wirelessMode=1"),
    )
    for radio, message in cases:
        fake = FakeAdapter()

        result = NetgearPlatformPort(fake).reconcile(
            _cmd(radios=(radio,)), netgear_capabilities()
        )

        assert result.applied is False
        assert result.changed is False
        assert message in result.error
        assert fake.desired is None


def test_reconcile_distinguishes_idempotent_state_from_unsupported_changes():
    from dataclasses import replace

    fake = FakeAdapter()
    port = NetgearPlatformPort(fake)
    enabled = RadioConfig(RadioBand.TWO_G, enabled=True)

    result = port.reconcile(_cmd(radios=(enabled,)), netgear_capabilities())

    assert result.applied is True
    assert result.changed is False
    assert fake.desired is None

    fake.state["2.4G"] = replace(fake.state["2.4G"], enabled=False)
    result = port.reconcile(_cmd(radios=(enabled,)), netgear_capabilities())

    assert result.applied is False
    assert "radioEnable=True" in result.error
    assert fake.desired is None

    fake = FakeAdapter()
    fake.state["2.4G"] = replace(fake.state["2.4G"], broadcast=False)
    result = NetgearPlatformPort(fake).reconcile(
        _cmd(wlans=(_wlan(),)), netgear_capabilities()
    )

    assert result.applied is False
    assert "ssidBcast=True" in result.error
    assert fake.desired is None


def test_reconcile_rejects_actionable_wlan_settings_without_ssid_writes():
    from dataclasses import replace

    base = _wlan()
    psk_base = _wlan(psk="secret123")
    cases = (
        (replace(base, operation=2), "WLAN operation=2"),
        (replace(base, broadcast=False), "ssidBcast=False"),
        (replace(base, client_isolation=True), "ssidIsolation=True"),
        (
            replace(base, security=replace(base.security, security_mode=0)),
            "securityMode=0",
        ),
        (
            replace(psk_base, security=replace(psk_base.security, security_mode=0)),
            "pskKey with securityMode=0",
        ),
        (
            replace(base, security=replace(base.security, psk_version=1)),
            "pskVer=1",
        ),
        (
            replace(psk_base, security=replace(psk_base.security, psk_version=2)),
            "pskVer=2",
        ),
        (
            replace(base, security=replace(base.security, psk_cipher=2)),
            "pskCipher=2",
        ),
        (
            replace(base, security=replace(base.security, pmf_mode=1)),
            "pmfMode=1",
        ),
        (
            replace(base, security=replace(base.security, fast_roaming=True)),
            "fastTransition.enable11r=True",
        ),
        (
            replace(
                base,
                security=replace(base.security, radius_accounting={"enable": True}),
            ),
            "wpa enterprise unsupported",
        ),
    )
    for wlan, message in cases:
        fake = FakeAdapter()

        result = NetgearPlatformPort(fake).reconcile(
            _cmd(wlans=(wlan,)), netgear_capabilities()
        )

        assert result.applied is False
        assert result.changed is False
        assert message in result.error
        assert fake.desired is None


def test_reconcile_rejects_led_actions_and_portal_policy_with_portal_intent():
    from dataclasses import replace

    from open_omada_device_agent.contexts.device.domain import (
        LedConfig,
        WifiControlLedConfig,
    )
    from open_omada_device_agent.contexts.portal.domain import PortalFreePolicy

    portal_wlan = replace(_wlan(), portal=CaptivePortalIntent(enabled=True))
    cases = (
        (_cmd(led=LedConfig(enabled=False)), "led.enable=False"),
        (_cmd(led=LedConfig(locate=True)), "led.locate=True"),
        (
            _cmd(wifi_control_led=WifiControlLedConfig(enabled=False)),
            "wifiControlLed.enable=False",
        ),
        (
            _cmd(wifi_control_led=WifiControlLedConfig(is_pressed=True)),
            "wifiControlLed.isPressed=True",
        ),
        (
            _cmd(
                wlans=(portal_wlan,),
                portal_free_policy=PortalFreePolicy(
                    layer2_rules=({"value": "192.0.2.1"},)
                ),
            ),
            "portalFreePolicyConfig with rules",
        ),
        (
            _cmd(
                wlans=(portal_wlan,),
                portal_free_policy=PortalFreePolicy(url_rules=({"host": "example.com"},)),
            ),
            "portalFreePolicyConfig with rules",
        ),
    )
    for update, message in cases:
        fake = FakeAdapter()

        result = NetgearPlatformPort(fake).reconcile(update, netgear_capabilities())

        assert result.applied is False
        assert result.changed is False
        assert message in result.error
        assert fake.desired is None


def test_reconcile_combines_unsupported_errors_with_partial_adapter_result():
    class PartialAdapter(FakeAdapter):
        def reconcile(self, desired):
            self.desired = desired
            return NetgearReconcileResult(
                applied=True,
                changed=True,
                error="channel Auto on 5G unsupported on netgear",
            )

    fake = PartialAdapter()
    result = NetgearPlatformPort(fake).reconcile(
        _cmd(
            radios=(
                RadioConfig(RadioBand.TWO_G, channel_width=20, channel=6),
                RadioConfig(RadioBand.FIVE_G, channel=0),
            )
        ),
        netgear_capabilities(),
    )

    assert result.applied is False
    assert result.changed is True
    assert result.error == (
        "chanWidth=20 on 2g unsupported on netgear; "
        "channel Auto on 5G unsupported on netgear"
    )
    assert fake.desired.channels == (("2.4G", "6"), ("5G", "Auto"))


def test_reconcile_surfaces_state_read_failure_before_router_writes():
    class UnreadableAdapter(FakeAdapter):
        def read_state(self):
            raise RuntimeError("SOAP unavailable")

    fake = UnreadableAdapter()
    result = NetgearPlatformPort(fake).reconcile(
        _cmd(radios=(RadioConfig(RadioBand.TWO_G, enabled=True),)),
        netgear_capabilities(),
    )

    assert result.applied is False
    assert result.changed is False
    assert "cannot verify Netgear current state: SOAP unavailable" in result.error
    assert fake.desired is None


def test_reconcile_allows_only_security_modes_matching_state_without_a_psk_write():
    from dataclasses import replace

    base = _wlan()
    open_wlan = replace(base, security=replace(base.security, security_mode=0))
    psk_wlan = replace(base, security=replace(base.security, security_mode=3))

    fake = FakeAdapter()
    fake.state["2.4G"] = replace(fake.state["2.4G"], security="None")
    port = NetgearPlatformPort(fake)

    result = port.reconcile(_cmd(wlans=(open_wlan,)), netgear_capabilities())
    assert result.applied is True
    assert result.error == ""

    result = port.reconcile(_cmd(wlans=(psk_wlan,)), netgear_capabilities())
    assert result.applied is False
    assert "securityMode=3" in result.error

    fake = FakeAdapter()
    fake.state["2.4G"] = replace(fake.state["2.4G"], security="WPA2-PSK")
    result = NetgearPlatformPort(fake).reconcile(
        _cmd(wlans=(psk_wlan,)), netgear_capabilities()
    )
    assert result.applied is True
    assert result.error == ""
