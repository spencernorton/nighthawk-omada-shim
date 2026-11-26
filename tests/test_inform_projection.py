from open_omada_device_agent.adapters.outbound.openwrt.client_observations import (
    client_stats_payload,
)
from open_omada_device_agent.contexts.clients.domain import ClientPortalState, WirelessClientState
from open_omada_device_agent.projections.inform import InformAssembler, LanObservation


def test_inform_assembler_separates_observation_from_wire_projection():
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap", "isFactory": True},
        lan=LanObservation(rate=100.0, duplex=1, port="LAN"),
        clients=lambda: (WirelessClientState(mac="aa:bb:cc:dd:ee:ff"),),
        client_projection=lambda clients: [{"mac": clients[0].mac}],
        wireless_projection=lambda: {"wSettings_2G": {"ch": "6"}},
    )

    body = assembler.build(need_reply=True, uptime=12)

    assert body["deviceInfo"]["upTime"] == "0 days 00:00:12"
    assert body["deviceInfo"]["isFactory"] is False
    assert body["clients"] == [{"mac": "aa:bb:cc:dd:ee:ff"}]
    assert body["wSettings_2G"] == {"ch": "6"}


def test_inform_assembler_emits_required_zero_for_unknown_client_counters():
    observed = (
        WirelessClientState(mac="aa:bb:cc:dd:ee:10"),
        WirelessClientState(mac="aa:bb:cc:dd:ee:11", rx_bytes=0, tx_bytes=0),
    )
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap"},
        lan=LanObservation(rate=100.0, duplex=1, port="LAN"),
        clients=lambda: observed,
        client_projection=client_stats_payload,
        wireless_projection=lambda: {},
    )

    body = assembler.build(need_reply=False, uptime=0)
    unknown, measured_zero = body["clients"]

    assert observed[0].rx_bytes is None
    assert observed[0].tx_bytes is None
    assert unknown["down"] == 0
    assert unknown["up"] == 0
    assert measured_zero["down"] == 0
    assert measured_zero["up"] == 0


def test_inform_assembler_projects_portal_auth_clients():
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap"},
        lan=LanObservation(rate=100.0, duplex=1, port="LAN"),
        clients=lambda: (
            WirelessClientState(
                mac="aa:bb:cc:dd:ee:ff",
                portal_state=ClientPortalState.AUTHENTICATED,
            ),
            WirelessClientState(mac="02:00:00:00:00:02"),
        ),
        client_projection=lambda clients: [
            {"mac": "AA-BB-CC-DD-EE-FF"},
            {"mac": "02-00-00-00-00-02"},
        ],
        wireless_projection=lambda: {},
    )

    body = assembler.build(need_reply=False, uptime=0)

    assert body["portalAuthClients"] == [{"mac": "AA-BB-CC-DD-EE-FF"}]


def test_inform_assembler_preserves_device_uptime_when_adapter_reports_it():
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap", "upTime": 99},
        lan=LanObservation(rate=100.0, duplex=1, port="LAN"),
        clients=lambda: (),
        client_projection=lambda clients: [],
        wireless_projection=lambda: {},
    )

    body = assembler.build(need_reply=False, uptime=12)

    assert body["deviceInfo"]["upTime"] == "0 days 00:01:39"



def test_ecsp_uptime_round_trips_omada_tokenizer_contract():
    from open_omada_device_agent.util.uptime import format_ecsp_uptime, parse_ecsp_uptime

    assert format_ecsp_uptime(0) == "0 days 00:00:00"
    assert format_ecsp_uptime(90061) == "1 days 01:01:01"
    assert parse_ecsp_uptime(format_ecsp_uptime(90061)) == 90061



def test_inform_assembler_emits_integer_lan_rate_and_10g_uplink_port_status():
    assembler = InformAssembler(
        device_info=lambda: {"name": "Nighthawk-AP-1"},
        lan=LanObservation(rate=10000.0, duplex=1, port="LAN"),
        clients=lambda: (),
        client_projection=lambda clients: [],
        wireless_projection=lambda: {},
    )

    body = assembler.build(need_reply=False, uptime=60)

    assert body["lanInfo"] == {"rate": "10000", "duplex": 1, "port": "LAN"}
    assert body["uplinkPortStatus"] == [
        {"port": "LAN", "portType": 1, "duplex": 1, "link": 1, "speed": 10000}
    ]


def test_inform_assembler_preserves_nonintegral_lan_rate():
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap"},
        lan=LanObservation(rate=10000.5, duplex=1, port="LAN"),
        clients=lambda: (),
        client_projection=lambda clients: [],
        wireless_projection=lambda: {},
    )

    body = assembler.build(need_reply=False, uptime=60)

    assert body["lanInfo"]["rate"] == "10000.5"


def test_inform_assembler_preserves_unavailable_router_metric_omission():
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap"},
        lan=LanObservation(rate=100.0, duplex=1, port="LAN"),
        clients=lambda: (),
        client_projection=lambda clients: [],
        wireless_projection=lambda: {},
    )

    info = assembler.build(need_reply=False, uptime=0)["deviceInfo"]

    assert "cpuUti" not in info
    assert "memUti" not in info


def test_inform_assembler_preserves_measured_zero_router_memory():
    assembler = InformAssembler(
        device_info=lambda: {"name": "ap", "memUti": 0},
        lan=LanObservation(rate=100.0, duplex=1, port="LAN"),
        clients=lambda: (),
        client_projection=lambda clients: [],
        wireless_projection=lambda: {},
    )

    info = assembler.build(need_reply=False, uptime=0)["deviceInfo"]

    assert info["memUti"] == 0
    assert "cpuUti" not in info
