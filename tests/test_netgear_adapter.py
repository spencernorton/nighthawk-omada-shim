from unittest.mock import Mock

import pytest

from open_omada_device_agent.adapters.outbound.netgear.adapter import (
    DesiredMainWlan,
    NetgearAdapter,
    netgear_capabilities,
)
from open_omada_device_agent.adapters.outbound.netgear.platform import NetgearPlatformPort
from open_omada_device_agent.adapters.outbound.netgear.soap import BandState
from open_omada_device_agent.ap_config import parse_config_body
from open_omada_device_agent.application.configuration import ApplyDeviceConfiguration


class StubClient:
    def __init__(self, state):
        self._state = state
        self.state_calls = []
        self.channel_calls = []

    def band_state(self, band):
        self.state_calls.append(band)
        return self._state[band]

    def set_channel(self, band, channel):
        self.channel_calls.append((band, channel))


def _state(channel="1"):
    return {
        band: BandState(
            band=band,
            ssid="ExampleNet",
            enabled=True,
            broadcast=True,
            channel=channel,
            wireless_mode="",
            security="",
            mac="",
        )
        for band in ("2.4G", "5G", "6G")
    }


def _configuration_use_case(adapter):
    port = NetgearPlatformPort(adapter)
    return ApplyDeviceConfiguration(
        capability_detector=netgear_capabilities,
        platform_ports=(port,),
        command_ports=(port,),
    )


def test_auto_channel_change_is_unsupported_and_does_not_call_soap():
    stub = StubClient(_state(channel="1"))

    result = NetgearAdapter(stub).reconcile(
        DesiredMainWlan(channels=(("2.4G", "Auto"),))
    )

    assert result.changed is False
    assert result.calls == 0
    assert "channel Auto on 2.4G unsupported" in result.error
    assert stub.channel_calls == []


def test_auto_channel_already_active_is_an_idempotent_success():
    stub = StubClient(_state(channel="0"))

    result = NetgearAdapter(stub).reconcile(
        DesiredMainWlan(channels=(("2.4G", "Auto"),))
    )

    assert result.applied is True
    assert result.changed is False
    assert result.error == ""
    assert stub.channel_calls == []


def test_numeric_channel_applies_while_auto_is_reported_unsupported():
    stub = StubClient(_state(channel="1"))

    result = NetgearAdapter(stub).reconcile(
        DesiredMainWlan(channels=(("2.4G", "Auto"), ("5G", "36")))
    )

    assert result.changed is True
    assert result.calls == 1
    assert result.error == "channel Auto on 2.4G unsupported on netgear"
    assert stub.channel_calls == [("5G", "36")]


def test_controller_result_rejects_fixed_to_auto_channel_noop():
    stub = StubClient(_state(channel="1"))
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body({"wirelessBasic_2G": {"channel": 0}})

    result = use_case.execute(update)

    assert result.applied is False
    assert result.changed is False
    assert "channel Auto on 2.4G unsupported" in result.error
    assert stub.channel_calls == []


def test_controller_result_rejects_portal_only_config_without_router_writes():
    stub = StubClient(_state())
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body({"portalConfigList": [{"siteName": "HQ"}]})

    result = use_case.execute(update)

    assert result.applied is False
    assert "captive portal unsupported" in result.error
    assert stub.state_calls == []
    assert stub.channel_calls == []


def test_wpa2_only_request_is_rejected_without_soap_writes():
    class PskClient(StubClient):
        def __init__(self, state):
            super().__init__(state)
            self.psk_calls = []

        def set_psk(self, band, ssid, passphrase):
            self.psk_calls.append((band, ssid, passphrase))

    stub = PskClient(_state())
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body(
        {
            "ssid_2G": {
                "ssid": [
                    {
                        "ssidName": "ExampleNet",
                        "securityMode": 3,
                        "pskVer": 2,
                        "pskKey": "secret123",
                    }
                ]
            }
        }
    )

    result = use_case.execute(update)

    assert result.applied is False
    assert result.changed is False
    assert "pskVer=2" in result.error
    assert stub.psk_calls == []
    assert stub.channel_calls == []


def test_passphrase_without_ssid_is_rejected_before_router_access():
    stub = StubClient(_state())

    result = NetgearAdapter(stub).reconcile(DesiredMainWlan(passphrase="secret123"))

    assert result.applied is False
    assert result.changed is False
    assert "requires an SSID" in result.error
    assert stub.state_calls == []


def test_controller_result_preserves_partial_changes_and_all_failure_reasons():
    class FailingClient(StubClient):
        def set_channel(self, band, channel):
            super().set_channel(band, channel)
            if band == "6G":
                raise RuntimeError("SOAP ResponseCode=402")

    stub = FailingClient(_state(channel="1"))
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body(
        {
            "wirelessBasic_2G": {"channel": 0},
            "wirelessBasic_5G": {"channel": 36},
            "wirelessBasic_6G": {"channel": 40},
        }
    )

    result = use_case.execute(update)

    assert result.applied is False
    assert result.changed is True
    assert result.error == (
        "channel Auto on 2.4G unsupported on netgear; SOAP ResponseCode=402"
    )
    assert stub.channel_calls == [("5G", "36"), ("6G", "40")]


def test_controller_result_applies_fixed_channel_while_rejecting_radio_width():
    stub = StubClient(_state(channel="1"))
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body(
        {"wirelessBasic_5G": {"chanWidth": 20, "channel": 36}}
    )

    result = use_case.execute(update)

    assert result.applied is False
    assert result.changed is True
    assert result.error == "chanWidth=20 on 5g unsupported on netgear"
    assert stub.channel_calls == [("5G", "36")]


@pytest.mark.parametrize("vid", [1, 37, 4094])
@pytest.mark.parametrize("guest", [False, True])
def test_rejects_explicit_ssid_vlan_before_router_access(vid, guest):
    stub = StubClient(_state())
    wlan = {"ssidName": "Guest" if guest else "ExampleNet", "vlanId": vid}
    if guest:
        wlan["ssidIsolation"] = True
    update = parse_config_body({"ssid_2G": {"ssid": [wlan]}})

    result = _configuration_use_case(NetgearAdapter(stub)).execute(update)

    assert result.applied is False
    assert result.changed is False
    assert f"ssid vlan {vid} unsupported on netgear" in result.error
    assert stub.state_calls == []


@pytest.mark.parametrize("vlan", [{}, {"vlanId": 0}])
def test_accepts_untagged_ssid(vlan):
    stub = StubClient(_state())
    update = parse_config_body({"ssid_5G": {"ssid": [{"ssidName": "ExampleNet", **vlan}]}})

    result = _configuration_use_case(NetgearAdapter(stub)).execute(update)

    assert result.applied is True
    assert result.changed is False
    assert result.error == ""


def test_explicit_vlan_blocks_shared_wlan_write_and_preserves_independent_channel_change():
    stub = StubClient(_state())
    stub.set_psk = Mock()
    wlan = {"ssidName": "NewName", "pskKey": "fixture-passphrase"}
    update = parse_config_body({
        "ssid_2G": {"ssid": [{**wlan, "vlanId": 1}]},
        "ssid_5G": {"ssid": [wlan]},
        "wirelessBasic_6G": {"channel": 37},
    })

    result = _configuration_use_case(NetgearAdapter(stub)).execute(update)

    assert result.applied is False
    assert result.changed is True
    assert "ssid vlan 1 unsupported on netgear" in result.error
    stub.set_psk.assert_not_called()
    assert stub.channel_calls == [("6G", "37")]


def test_controller_result_rejects_dynamic_vlan_pools_and_enabled_option82():
    cases = (
        ({"dyVlanMode": 1}, "dynamic VLAN mode=1"),
        ({"vlanPoolIds": ["pool-1"]}, "VLAN pools"),
        ({"dhcpOp82": {"option82En": True}}, "DHCP Option 82 enabled"),
    )
    for vlan_config, message in cases:
        stub = StubClient(_state())
        use_case = _configuration_use_case(NetgearAdapter(stub))
        update = parse_config_body(
            {"ssid_2G": {"ssid": [{"ssidName": "ExampleNet", **vlan_config}]}}
        )

        result = use_case.execute(update)

        assert result.applied is False
        assert result.changed is False
        assert message in result.error
        assert stub.state_calls == []
        assert stub.channel_calls == []


def test_controller_result_accepts_disabled_vlan_and_option82_defaults():
    stub = StubClient(_state())
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body(
        {
            "ssid_2G": {
                "ssid": [
                    {
                        "ssidName": "ExampleNet",
                        "dyVlanMode": 0,
                        "vlanPoolIds": [],
                        "dhcpOp82": {"option82En": False},
                    }
                ]
            }
        }
    )

    result = use_case.execute(update)

    assert result.applied is True
    assert result.changed is False
    assert result.error == ""
    assert stub.channel_calls == []


def test_rejected_band_skips_global_psk_write_but_applies_fixed_channel():
    class PskClient(StubClient):
        def __init__(self, state):
            super().__init__(state)
            self.psk_calls = []

        def current_psk(self, band):
            return "old-secret"

        def set_psk(self, band, ssid, passphrase):
            self.psk_calls.append((band, ssid, passphrase))

    stub = PskClient(_state(channel="1"))
    use_case = _configuration_use_case(NetgearAdapter(stub))
    update = parse_config_body(
        {
            "ssid_2G": {
                "ssid": [
                    {
                        "ssidName": "ExampleNet",
                        "securityMode": 3,
                        "pskVer": 2,
                        "pskKey": "secret123",
                    }
                ]
            },
            "ssid_5G": {
                "ssid": [
                    {
                        "ssidName": "ExampleNet",
                        "securityMode": 3,
                        "pskVer": 3,
                        "pskKey": "secret123",
                    }
                ]
            },
            "wirelessBasic_6G": {"channel": 36},
        }
    )

    result = use_case.execute(update)

    assert result.applied is False
    assert result.changed is True
    assert "pskVer=2" in result.error
    assert stub.psk_calls == []
    assert stub.channel_calls == [("6G", "36")]
