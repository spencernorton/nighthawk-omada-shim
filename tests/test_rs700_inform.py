from open_omada_device_agent.adapters.outbound.netgear.platform import (
    NetgearClientSource,
    NetgearWirelessInform,
)
from open_omada_device_agent.adapters.outbound.netgear.soap import AttachedClient, BandState
from open_omada_device_agent.adapters.outbound.openwrt.client_observations import (
    client_stats_payload,
)
from open_omada_device_agent.projections.inform import InformAssembler, LanObservation


class Rs700AdapterStub:
    def __init__(self):
        self.state = {
            "2.4G": BandState(
                band="2.4G",
                ssid="ExampleNet",
                enabled=True,
                broadcast=True,
                channel="Auto",
                wireless_mode="688Mbps",
                security="WPA2",
                mac="02:00:00:00:A1:02",
            ),
            "5G": BandState(
                band="5G",
                ssid="ExampleNet",
                enabled=True,
                broadcast=True,
                channel="44",
                wireless_mode="5765Mbps",
                security="WPA2",
                mac="02:00:00:00:A1:03",
            ),
            "6G": BandState(
                band="6G",
                ssid="ExampleNet",
                enabled=True,
                broadcast=True,
                channel="69",
                wireless_mode="11529Mbps",
                security="WPA3",
                mac="02:00:00:00:A1:04",
            ),
        }
        self.clients = [
            AttachedClient(
                ip="192.0.2.10",
                name="Laptop",
                mac="AA:BB:CC:DD:EE:10",
                connection="wireless",
                link_rate_mbps=286,
                signal_percent=60,
                band="2.4G",
                ssid="ExampleNet",
            ),
            AttachedClient(
                ip="192.0.2.11",
                name="Plug",
                mac="AA:BB:CC:DD:EE:11",
                connection="wireless",
                link_rate_mbps=72,
                signal_percent=55,
                band="2.4G",
                ssid="ExampleIoT",
            ),
            AttachedClient(
                ip="192.0.2.12",
                name="Phone",
                mac="AA:BB:CC:DD:EE:12",
                connection="wireless",
                link_rate_mbps=1201,
                signal_percent=75,
                band="5G",
                ssid="ExampleNet",
            ),
            AttachedClient(
                ip="192.0.2.13",
                name="Tablet",
                mac="AA:BB:CC:DD:EE:13",
                connection="wireless",
                link_rate_mbps=2400,
                signal_percent=80,
                band="6G",
                ssid="ExampleNet",
            ),
            AttachedClient(
                ip="192.0.2.14",
                name="Server",
                mac="AA:BB:CC:DD:EE:14",
                connection="wired",
                link_rate_mbps=1000,
                signal_percent=None,
            ),
        ]

    def read_state(self):
        return dict(self.state)

    def read_clients(self):
        return list(self.clients)


def _build_rs700_inform():
    adapter = Rs700AdapterStub()
    assembler = InformAssembler(
        device_info=lambda: {
            "name": "Nighthawk-AP-1",
            "model": "EAP770",
            "modelVersion": "2.0",
            "mainMac": "02-00-00-00-00-01",
            "upTime": 312055,
            "isFactory": True,
        },
        lan=LanObservation(rate=10000.0, duplex=1, port="LAN"),
        clients=NetgearClientSource(adapter),
        client_projection=client_stats_payload,
        wireless_projection=NetgearWirelessInform(
            adapter,
            ssid_ids={(band, "ExampleNet"): 42 for band in ("2.4G", "5G", "6G")},
        ),
    )
    return assembler.build(need_reply=True, uptime=12)


def test_rs700_inform_preserves_ap_radio_ssid_and_uplink_contracts():
    body = _build_rs700_inform()

    assert body["needReply"] == 1
    assert body["deviceInfo"]["isFactory"] is False
    assert body["deviceInfo"]["upTime"] == "3 days 14:40:55"
    assert body["lanInfo"] == {"rate": "10000", "duplex": 1, "port": "LAN"}
    assert body["uplinkPortStatus"] == [
        {"port": "LAN", "portType": 1, "duplex": 1, "link": 1, "speed": 10000}
    ]

    expected_radios = {
        "2G": ("0", "40MHz", "25dBm", "688.0Mbps", 2),
        "5G": ("44", "160MHz", "25dBm", "5765.0Mbps", 1),
        "6G": ("69", "320MHz", "23dBm", "11529.0Mbps", 1),
    }
    for suffix, (channel, width, power, rate, station_count) in expected_radios.items():
        settings = body[f"wSettings_{suffix}"]
        assert settings["ch"] == channel
        assert settings["bw"] == width
        assert settings["txPower"] == power
        assert settings["rdMode"] == "11be"
        assert settings["txR"] == rate
        assert settings["staNum"] == station_count
        assert all(
            isinstance(settings[key], int)
            for key in ("txUti", "rxUti", "interUti", "busyUti")
        )

    expected_bssids = {
        "2G": "02-00-00-00-A1-02",
        "5G": "02-00-00-00-A1-03",
        "6G": "02-00-00-00-A1-04",
    }
    for suffix, bssid in expected_bssids.items():
        assert body[f"ssidStats_{suffix}"] == [
            {
                "id": 42,
                "ssid": "ExampleNet",
                "bssid": bssid,
                "clntNum": 1,
            }
        ]


def test_rs700_inform_projects_wireless_clients_with_valid_rids_and_real_metadata():
    body = _build_rs700_inform()
    clients = {client["name"]: client for client in body["clients"]}

    assert set(clients) == {"Laptop", "Plug", "Phone", "Tablet"}
    assert {client["rid"] for client in clients.values()} == {0, 1, 3}
    assert clients["Laptop"]["rid"] == 0
    assert clients["Plug"]["rid"] == 0
    assert clients["Phone"]["rid"] == 1
    assert clients["Tablet"]["rid"] == 3
    assert clients["Plug"]["ssid"] == "ExampleIoT"
    assert clients["Phone"]["ssid"] == "ExampleNet"
    assert clients["Laptop"]["ip"] == "192.0.2.10"
    assert clients["Laptop"]["mac"] == "AA-BB-CC-DD-EE-10"
    assert clients["Phone"]["rxR"] == 1201000
    assert clients["Phone"]["txR"] == 1201000
    assert clients["Tablet"]["rxR"] == 2400000
    assert clients["Tablet"]["txR"] == 2400000

    for client in clients.values():
        assert client["down"] == 0
        assert client["up"] == 0
        for unavailable in (
            "rids", "snr", "vid", "rxP", "txP", "aTime", "portalStatus"
        ):
            assert unavailable not in client
    assert "portalAuthClients" not in body
