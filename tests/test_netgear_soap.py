"""Fixture tests for the Netgear SOAP southbound adapter.

Fixtures are sanitized recordings of the live RS700 SOAP shapes proven in
plan Step 1 (SOAPVersion 3.84): per-band GetInfo, GetAttachDevice payloads,
and same-value setter round-trips.
"""
from pathlib import Path

import pytest

from open_omada_device_agent.adapters.outbound.netgear.adapter import (
    DesiredMainWlan,
    NetgearAdapter,
    netgear_capabilities,
)
from open_omada_device_agent.adapters.outbound.netgear.soap import (
    NetgearSoapClient,
    SoapError,
    parse_attach_devices,
    parse_band_state,
    response_fields,
    signal_percent_to_dbm,
)

FIXTURES = Path(__file__).parent / "fixtures" / "netgear"
OK_XML = ('<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/">'
          '<soap-env:Body><m:R xmlns:m="urn:NETGEAR-ROUTER:service:DeviceInfo:1">'
          '<ResponseCode>000</ResponseCode></m:R></soap-env:Body></soap-env:Envelope>')


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, body, headers):
        self.requests.append((url, body.decode(), headers))
        text = self.responses.pop(0)
        cookie = "session=abc" if "SOAPLogin" in body.decode() else ""
        return text, cookie


def test_parse_band_state_from_live_shape():
    fields = response_fields((FIXTURES / "get_info_24g.xml").read_text())
    state = parse_band_state("2.4G", fields)
    assert state.ssid == "ExampleNet"
    assert state.enabled and state.broadcast
    assert state.channel == "01"
    assert state.mac == "0011223344A0"


def test_parse_attach_devices_wireless_and_wired():
    fields = response_fields((FIXTURES / "attach_devices.xml").read_text())
    clients = parse_attach_devices(fields["NewAttachDevice"])
    assert len(clients) == 4
    phone, plug, fast, server = clients
    assert phone.connection == "wireless" and phone.signal_percent == 37
    assert phone.link_rate_mbps == 1407
    assert plug.signal_percent == 82
    assert fast.link_rate_mbps == 2345
    # wired placeholder 100 must not become an RF reading
    assert server.connection == "wired"
    assert server.signal_percent is None and server.signal_dbm is None


def test_signal_conversion_is_documented_approximation():
    assert signal_percent_to_dbm(37) == -82
    assert signal_percent_to_dbm(82) == -59
    assert signal_percent_to_dbm(100) == -50


def test_parse_attach_devices_tolerates_empty():
    assert parse_attach_devices("") == []
    assert parse_attach_devices("0@") == []


def test_login_preserves_xml_characters_in_password():
    from xml.etree import ElementTree

    transport = FakeTransport([OK_XML])
    password = "a&b<c>"
    NetgearSoapClient("192.0.2.1", "admin", password, transport=transport).login()
    request = ElementTree.fromstring(transport.requests[0][1])
    assert request.findtext(".//Password") == password


def test_client_login_then_reads_with_cookie():
    transport = FakeTransport([OK_XML, (FIXTURES / "attach_devices.xml").read_text()])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)
    client.login()
    clients = client.attached_clients()
    assert len(clients) == 4
    assert transport.requests[1][2].get("Cookie") == "session=abc"


def test_client_raises_on_router_error_code():
    # 402 is the router's reject code; 401 means session-expiry and is
    # retried after re-login (covered by the relogin tests below).
    err_xml = OK_XML.replace("000", "402")
    transport = FakeTransport([err_xml])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)
    with pytest.raises(SoapError):
        client.device_info()


def test_capabilities_refuse_unemulatable_features():
    caps = netgear_capabilities()
    assert caps.supports_wlan_config and caps.supports_wpa2_psk
    assert not caps.supports_ssid_vlan
    assert not caps.supports_portal
    assert not caps.supports_wpa_enterprise
    assert caps.max_ssids == 1


class StubClient:
    def __init__(self, state, psk=""):
        self._state = state
        self._psk = psk
        self.psk_calls = []
        self.channel_calls = []

    def current_psk(self, band):
        return self._psk

    def band_state(self, band):
        return self._state[band]

    def attached_clients(self):
        return []

    def set_psk(self, band, ssid, passphrase):
        self.psk_calls.append((band, ssid))

    def set_channel(self, band, channel):
        self.channel_calls.append((band, channel))


def _state(ssid="ExampleNet", channel="01"):
    from open_omada_device_agent.adapters.outbound.netgear.soap import BandState
    return {b: BandState(band=b, ssid=ssid, enabled=True, broadcast=True,
                         channel=channel, wireless_mode="", security="", mac="")
            for b in ("2.4G", "5G", "6G")}


def test_reconcile_auto_channel_is_logged_noop_not_a_setter_call():
    stub = StubClient(_state(channel="01"))
    adapter = NetgearAdapter(stub)
    result = adapter.reconcile(DesiredMainWlan(
        ssid="ExampleNet", channels=(("2.4G", "Auto"), ("5G", "Auto"))))
    assert result.applied
    assert stub.channel_calls == []  # SOAP rejects "Auto" live (402)


def test_reconcile_numeric_channel_compare_ignores_zero_padding():
    stub = StubClient(_state(channel="01"))
    adapter = NetgearAdapter(stub)
    result = adapter.reconcile(DesiredMainWlan(
        ssid="ExampleNet", channels=(("2.4G", "1"),)))
    assert result.applied and stub.channel_calls == []
    result = adapter.reconcile(DesiredMainWlan(
        ssid="ExampleNet", channels=(("2.4G", "6"),)))
    assert result.applied and stub.channel_calls == [("2.4G", "6")]


def test_reconcile_noop_when_already_matching():
    adapter = NetgearAdapter(StubClient(_state()))
    result = adapter.reconcile(DesiredMainWlan(ssid="ExampleNet",
                                               channels=(("2.4G", "01"),)))
    assert result.applied and not result.changed and result.calls == 0


def test_reconcile_skips_psk_setter_when_already_matching():
    stub = StubClient(_state(), psk="secret123")
    adapter = NetgearAdapter(stub)
    result = adapter.reconcile(DesiredMainWlan(ssid="ExampleNet", passphrase="secret123"))
    assert result.applied and not result.changed
    assert stub.psk_calls == []


def test_reconcile_rejects_rename_without_passphrase():
    adapter = NetgearAdapter(StubClient(_state()))
    result = adapter.reconcile(DesiredMainWlan(ssid="NewName"))
    assert not result.applied
    assert "passphrase" in result.error


def test_parse_attach_devices_detailed_bands_and_ssids():
    from open_omada_device_agent.adapters.outbound.netgear.soap import (
        parse_attach_devices_detailed,
    )
    clients = parse_attach_devices_detailed(
        (FIXTURES / "attach_devices2.xml").read_text())
    assert len(clients) == 4
    phone, laptop, sensor, server = clients
    assert phone.connection == "wireless" and phone.band == "2.4G"
    assert phone.ssid == "ExampleNet" and phone.signal_percent == 45
    assert laptop.band == "6G" and laptop.link_rate_mbps == 2400
    # Guest/IoT ConnectionType ("2.4GHz - Guest") maps to wireless 2.4G with its own SSID and fingerprint metadata
    assert sensor.connection == "wireless"
    assert sensor.ssid == "ExampleIoT" and sensor.band == "2.4G"
    assert sensor.device_type_name == "IoT (Generic)"
    assert sensor.device_brand == "ExampleCorp"
    assert sensor.device_model == "SmartPlug-1"
    assert server.connection == "wired" and server.band == ""
    assert server.signal_percent is None and server.signal_dbm is None


def test_call_relogs_in_once_on_session_expiry():
    expired = OK_XML.replace("<ResponseCode>000</ResponseCode>",
                             "<ResponseCode>401</ResponseCode>")
    transport = FakeTransport([OK_XML, expired, OK_XML, OK_XML])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)
    client.login()
    # First GetInfo sees 401 (expired cookie), re-logs in, retries, succeeds
    assert client.call("DeviceInfo", "GetInfo")["ResponseCode"] == "000"
    assert len(transport.requests) == 4  # login, 401, re-login, retry


def test_call_does_not_loop_on_persistent_401():
    expired = OK_XML.replace("<ResponseCode>000</ResponseCode>",
                             "<ResponseCode>401</ResponseCode>")
    transport = FakeTransport([OK_XML, expired, OK_XML, expired])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)
    client.login()
    with pytest.raises(SoapError, match="401"):
        client.call("DeviceInfo", "GetInfo")
    assert len(transport.requests) == 4  # one retry only


def test_detailed_clients_via_client_with_v1_fallback():
    fixture = (FIXTURES / "attach_devices2.xml").read_text()
    transport = FakeTransport([OK_XML, fixture])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)
    client.login()
    clients = client.attached_clients_detailed()
    assert [c.band for c in clients] == ["2.4G", "6G", "2.4G", ""]



def test_parse_wireless_mode_mbps_and_netgear_uptime():
    from open_omada_device_agent.adapters.outbound.netgear.soap import (
        parse_netgear_uptime,
        parse_wireless_mode_mbps,
    )

    assert parse_wireless_mode_mbps("688Mbps") == 688
    assert parse_wireless_mode_mbps("5765Mbps") == 5765
    assert parse_wireless_mode_mbps("11529Mbps") == 11529
    assert parse_wireless_mode_mbps("m") is None
    assert parse_wireless_mode_mbps("") is None

    assert parse_netgear_uptime(" 3 days 09:01:10") == 3 * 86400 + 9 * 3600 + 60 + 10
    assert parse_netgear_uptime("04:05:06") == 4 * 3600 + 5 * 60 + 6
    assert parse_netgear_uptime("") is None


def test_sys_uptime_seconds_queries_device_info():
    uptime_xml = (
        '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap-env:Body><m:GetSysUpTimeResponse xmlns:m="urn:NETGEAR-ROUTER:service:DeviceInfo:1">'
        "<SysUpTime> 3 days 09:01:10</SysUpTime>"
        "</m:GetSysUpTimeResponse><ResponseCode>000</ResponseCode></soap-env:Body></soap-env:Envelope>"
    )
    transport = FakeTransport([OK_XML, uptime_xml])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)
    client.login()
    assert client.sys_uptime_seconds() == 291670


def test_band_state_exposes_recorded_fields_and_explicit_absence():
    fields = response_fields((FIXTURES / "get_info_24g.xml").read_text())
    state = parse_band_state("2.4G", fields)
    assert state.status == "Up"
    assert state.region == "US"
    assert state.wpa_encryption_modes == "WPA2/WPA3-Personal"

    missing = parse_band_state("5G", {})
    assert missing.status is None
    assert missing.region is None
    assert missing.wpa_encryption_modes is None


def test_detailed_clients_expose_reported_ap_mac():
    from open_omada_device_agent.adapters.outbound.netgear.soap import (
        parse_attach_devices_detailed,
    )

    clients = parse_attach_devices_detailed(
        (FIXTURES / "attach_devices2.xml").read_text())
    assert all(client.reported_ap_mac == "02:00:00:00:A0:01" for client in clients)


def test_detailed_parser_handles_namespaces_and_unknown_values():
    from open_omada_device_agent.adapters.outbound.netgear.soap import (
        parse_attach_devices_detailed,
    )

    xml_text = """
    <NewAttachDevice xmlns="urn:NETGEAR-ROUTER:service:DeviceInfo:1">
      <Device>
        <MAC>aa:bb:cc:dd:ee:ff</MAC>
        <ConnectionType>Unrecognized</ConnectionType>
        <Linkspeed>not-reported</Linkspeed>
        <SignalStrength>101</SignalStrength>
      </Device>
      <Device><Name>missing client identity</Name></Device>
    </NewAttachDevice>
    """
    clients = parse_attach_devices_detailed(xml_text)
    assert len(clients) == 1
    client = clients[0]
    assert client.mac == "AA:BB:CC:DD:EE:FF"
    assert client.connection == "unknown" and client.band == ""
    assert client.link_rate_mbps is None
    assert client.signal_percent is None and client.signal_dbm is None
    assert client.reported_ap_mac is None


def test_attach_devices_rejects_non_decimal_and_out_of_range_numbers():
    clients = parse_attach_devices(
        "1@1;192.0.2.10;Device;AA:BB:CC:DD:EE:FF;wireless;²;105;Allow")
    assert len(clients) == 1
    assert clients[0].link_rate_mbps is None
    assert clients[0].signal_percent is None


def test_system_info_preserves_load_average_and_free_memory_semantics():
    from open_omada_device_agent.adapters.outbound.netgear.soap import parse_system_info

    info = parse_system_info({
        "NewCPUUtilization": "164",
        "NewPhysicalMemory": "256",
        "NewMemoryUtilization": "61",
        "NewPhysicalFlash": "128",
        "NewAvailableFlash": "128.00",
    })

    assert info.load_average_x100 == 164
    assert info.free_memory_percent == 61
    assert info.used_memory_percent == 39


def test_system_info_preserves_measured_zero_used_memory():
    from open_omada_device_agent.adapters.outbound.netgear.soap import parse_system_info

    info = parse_system_info({"NewCPUUtilization": "0", "NewMemoryUtilization": "100"})

    assert info.load_average_x100 == 0
    assert info.used_memory_percent == 0


@pytest.mark.parametrize("raw", ["", "not-reported", "-1", "101", "1.5", "²"])
def test_system_info_rejects_malformed_or_out_of_range_memory(raw):
    from open_omada_device_agent.adapters.outbound.netgear.soap import parse_system_info

    info = parse_system_info({"NewCPUUtilization": "164", "NewMemoryUtilization": raw})

    assert info.free_memory_percent is None
    assert info.used_memory_percent is None


@pytest.mark.parametrize("raw", ["", "not-reported", "-1", "1.5", "²"])
def test_system_info_rejects_malformed_load_average(raw):
    from open_omada_device_agent.adapters.outbound.netgear.soap import parse_system_info

    assert parse_system_info({"NewCPUUtilization": raw}).load_average_x100 is None


def test_system_info_client_uses_authenticated_device_info_read():
    from open_omada_device_agent.adapters.outbound.netgear.soap import SystemInfo

    system_xml = (
        '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap-env:Body><m:GetSystemInfoResponse '
        'xmlns:m="urn:NETGEAR-ROUTER:service:DeviceInfo:1">'
        "<NewCPUUtilization>164</NewCPUUtilization>"
        "<NewPhysicalMemory>256</NewPhysicalMemory>"
        "<NewMemoryUtilization>61</NewMemoryUtilization>"
        "<NewPhysicalFlash>128</NewPhysicalFlash>"
        "<NewAvailableFlash>128.00</NewAvailableFlash>"
        "</m:GetSystemInfoResponse><ResponseCode>000</ResponseCode>"
        "</soap-env:Body></soap-env:Envelope>"
    )
    transport = FakeTransport([OK_XML, system_xml])
    client = NetgearSoapClient("192.0.2.1", "admin", "pw", transport=transport)

    client.login()
    info = client.system_info()

    assert info == SystemInfo(load_average_x100=164, free_memory_percent=61)
    assert transport.requests[1][2]["Cookie"] == "session=abc"
    assert transport.requests[1][2]["SOAPAction"].endswith(
        "DeviceInfo:1#GetSystemInfo"
    )
    assert "<m:GetSystemInfo" in transport.requests[1][1]
