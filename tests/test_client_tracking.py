from open_omada_device_agent.client_tracking import (
    client_stats_payload,
    clients_from_dhcp_leases,
    merge_associated_wireless_client_states,
    merge_wireless_client_states,
    parse_dnsmasq_leases,
)
from open_omada_device_agent.domain import RadioBand, WirelessClientState


def test_parse_dnsmasq_leases_and_merge_latest_by_mac():
    leases = parse_dnsmasq_leases(
        "\n".join(
            [
                "1000 aa:bb:cc:dd:ee:ff 192.0.2.10 phone 01:aabb",
                "1200 aa-bb-cc-dd-ee-ff 192.0.2.11 phone-new *",
                "900 02:00:00:00:00:02 192.0.2.12 * *",
            ]
        )
    )

    clients = clients_from_dhcp_leases(leases)

    assert len(clients) == 2
    assert clients[0].mac == "02:00:00:00:00:02"
    assert clients[0].hostname is None
    assert clients[1].mac == "aa:bb:cc:dd:ee:ff"
    assert clients[1].ipv4 == "192.0.2.11"
    assert clients[1].hostname == "phone-new"


def test_client_stats_payload_marks_wired_without_wireless_fields():
    clients = (
        WirelessClientState(
            mac="aa:bb:cc:dd:ee:10", ipv4="192.0.2.20", hostname="server",
            wireless=False,
        ),
    )
    payload = client_stats_payload(clients)
    # A wired client must not carry SSID/radio/RSSI markers: those are
    # what makes the controller label a client wireless.
    assert payload == [
        {"mac": "AA-BB-CC-DD-EE-10", "ip": "192.0.2.20", "name": "server",
         "down": 0, "up": 0}
    ]


def test_client_stats_payload_emits_required_zero_for_unknown_and_measured_zero():
    unknown = WirelessClientState(mac="aa:bb:cc:dd:ee:11")
    payload = client_stats_payload(
        (
            WirelessClientState(mac="aa:bb:cc:dd:ee:10", rx_bytes=0, tx_bytes=0),
            unknown,
        )
    )

    assert unknown.rx_bytes is None
    assert unknown.tx_bytes is None
    assert payload[0]["down"] == 0
    assert payload[0]["up"] == 0
    assert payload[1]["down"] == 0
    assert payload[1]["up"] == 0


def test_client_stats_payload_uses_controller_field_names():
    clients = (
        WirelessClientState(
            mac="aa:bb:cc:dd:ee:ff",
            ipv4="192.0.2.10",
            hostname="phone",
            ssid="guest",
            radio=RadioBand.TWO_G,
            rssi=-62,
            rx_bytes=123,
            tx_bytes=45,
            rx_packets=4,
            tx_packets=8,
            rx_rate=6500,
            tx_rate=7200,
            association_time=12,
        ),
    )

    payload = client_stats_payload(clients)

    assert payload == [
        {
            "mac": "AA-BB-CC-DD-EE-FF",
            "ip": "192.0.2.10",
            "name": "phone",
            "ssid": "guest",
            "rid": 0,
            "rssi": -62,
            "down": 123,
            "up": 45,
            "rxP": 4,
            "txP": 8,
            "rxR": 6500,
            "txR": 7200,
            "aTime": 12,
        }
    ]


def test_merge_wireless_client_states_preserves_dhcp_identity_and_hostapd_metrics():
    dhcp_clients = clients_from_dhcp_leases(
        parse_dnsmasq_leases("1000 aa:bb:cc:dd:ee:ff 192.0.2.10 phone *")
    )
    hostapd_clients = (
        WirelessClientState(
            mac="aa:bb:cc:dd:ee:ff",
            ssid="guest",
            radio=RadioBand.TWO_G,
            rssi=-60,
            rx_bytes=100,
            tx_bytes=20,
        ),
    )

    merged = merge_wireless_client_states(dhcp_clients, hostapd_clients)

    assert merged == (
        WirelessClientState(
            mac="aa:bb:cc:dd:ee:ff",
            ipv4="192.0.2.10",
            hostname="phone",
            ssid="guest",
            radio=RadioBand.TWO_G,
            rssi=-60,
            rx_bytes=100,
            tx_bytes=20,
        ),
    )


def test_merge_wireless_client_states_preserves_real_counters_with_unknown_overlay():
    observed = WirelessClientState(mac="aa:bb:cc:dd:ee:ff", rx_bytes=100, tx_bytes=20)

    merged = merge_wireless_client_states(
        (observed,), (WirelessClientState(mac="aa:bb:cc:dd:ee:ff"),)
    )

    assert (merged[0].rx_bytes, merged[0].tx_bytes) == (100, 20)


def test_merge_wireless_client_states_projects_measured_zero_overlay_counters():
    observed = WirelessClientState(mac="aa:bb:cc:dd:ee:ff", rx_bytes=100, tx_bytes=20)
    measured_zero = WirelessClientState(mac="aa:bb:cc:dd:ee:ff", rx_bytes=0, tx_bytes=0)

    merged = merge_wireless_client_states((observed,), (measured_zero,))

    assert client_stats_payload(merged) == [
        {"mac": "AA-BB-CC-DD-EE-FF", "down": 0, "up": 0}
    ]


def test_merge_associated_wireless_client_states_filters_stale_metadata_clients():
    associated_clients = (
        WirelessClientState(
            mac="aa:bb:cc:dd:ee:ff",
            ssid="guest",
            radio=RadioBand.TWO_G,
            rssi=-60,
        ),
    )
    metadata_clients = (
        WirelessClientState(mac="aa:bb:cc:dd:ee:ff", ipv4="192.0.2.10", hostname="phone"),
        WirelessClientState(mac="02:00:00:00:00:02", ipv4="192.0.2.20", hostname="stale"),
    )

    merged = merge_associated_wireless_client_states(associated_clients, metadata_clients)

    assert merged == (
        WirelessClientState(
            mac="aa:bb:cc:dd:ee:ff",
            ipv4="192.0.2.10",
            hostname="phone",
            ssid="guest",
            radio=RadioBand.TWO_G,
            rssi=-60,
        ),
    )
