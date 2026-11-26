"""Conservative AP profile caps: tri-band WiFi 7 vs legacy single-band."""
from dataclasses import replace

from open_omada_device_agent.adapters.outbound.openwrt.device_profile import (
    GenericOpenWrtAccessPointProfile,
)
from open_omada_device_agent.application.contracts import PlatformCapabilities
from open_omada_device_agent.bootstrap import AgentSettings
from open_omada_device_agent.contexts.wireless.domain import RadioBand

_TRI_BAND_CAPS = PlatformCapabilities(
    platform="netgear-soap",
    radio_bands=(RadioBand.TWO_G, RadioBand.FIVE_G, RadioBand.SIX_G),
    max_ssids=1,
    supports_wlan_config=True,
    supports_wpa2_psk=True,
)


def _profile(model: str, model_version: str, caps=_TRI_BAND_CAPS):
    settings = replace(
        AgentSettings.from_environment(), model=model, model_version=model_version
    )
    return GenericOpenWrtAccessPointProfile(
        settings, ip_address=lambda: "192.0.2.10", capabilities=caps
    )


def test_eap770_radio_cap_preserves_required_descriptors_without_mlo():
    caps = {c["radioId"]: c for c in _profile("EAP770", "2.0").radio_cap()}
    assert set(caps) == {0, 1, 3}
    for radio_id, max_pow in ((0, 25), (1, 25), (3, 23)):
        item = caps[radio_id]
        assert item["minPow"] == 4
        assert item["maxPow"] == max_pow
        assert item["limitMaxPow"] == 60
        assert item["mimo"] == 2
        assert item["ofdma"] == 1
        assert item["mcsLevel"] == 13
        assert item["supportMaxAssocClient"] == 128
        assert item["supportMlo"] is False


def test_eap770_radio_cap_ssid_count_follows_southbound():
    # Template advertises 8, but the Netgear southbound honours one main
    # SSID; the cap must not promise SSIDs the router cannot apply.
    caps = _profile("EAP770", "2.0").radio_cap()
    assert {c["supportSsidNum"] for c in caps} == {1}


def test_eap773_shares_conservative_triband_profile():
    assert _profile("EAP773", "1.0").radio_cap() == _profile("EAP770", "2.0").radio_cap()
    assert _profile("EAP773", "1.0").device_misc() == _profile("EAP770", "2.0").device_misc()


def test_eap770_device_misc_disables_unsupported_template_features():
    misc = _profile("EAP770", "2.0").device_misc()
    assert misc["support_5g"] is True
    assert misc["support_11ac"] is True
    assert misc["supportMesh"] == 0
    assert "meshWlanInterface" not in misc
    assert misc["supportRoaming"] == 0
    assert misc["supportDfs"] == 0
    assert misc["supportCluster"] == 0
    assert misc["minPower2G"] == 4 and misc["maxPower2G"] == 25
    assert misc["minPower5G"] == 4 and misc["maxPower5G"] == 25
    assert misc["category"] == "EAP"
    assert misc["modelType"] == "NORMAL"


def test_eap110_profile_unchanged():
    single = PlatformCapabilities(
        platform="netgear-soap",
        radio_bands=(RadioBand.TWO_G,),
        max_ssids=1,
        supports_wlan_config=True,
    )
    profile = _profile("EAP110", "4.0", caps=single)
    caps = profile.radio_cap()
    assert len(caps) == 1 and caps[0]["mimo"] == 1 and caps[0]["mcsLevel"] == 7
    misc = profile.device_misc()
    assert misc["supportMesh"] == 0 and misc["supportDfs"] == 0
    assert "support_5g" not in misc


def test_device_info_uses_southbound_uptime_when_available():
    settings = replace(AgentSettings.from_environment(), model="EAP770", model_version="2.0")
    profile = GenericOpenWrtAccessPointProfile(
        settings,
        ip_address=lambda: "192.0.2.159",
        capabilities=_TRI_BAND_CAPS,
        uptime_seconds=lambda: 291670,
    )
    info = profile.device_info()
    assert info["ip"] == "192.0.2.159"
    assert info["upTime"] == "3 days 09:01:10"


def test_device_info_uses_configured_hardware_and_firmware_versions():
    settings = replace(
        AgentSettings.from_environment(),
        model="EAP770",
        model_version="2.0",
        hardware_version="configured-hardware",
        firmware_version="configured-firmware",
    )
    profile = GenericOpenWrtAccessPointProfile(
        settings,
        ip_address=lambda: "192.0.2.10",
        capabilities=_TRI_BAND_CAPS,
    )

    info = profile.device_info()

    assert info["hardwareVersion"] == "configured-hardware"
    assert info["firmwareVersion"] == "configured-firmware"


def test_two_profiles_do_not_share_mutable_negotiation_state():
    first = _profile("EAP770", "2.0")
    second = _profile("EAP770", "2.0")

    first.device_misc()["supportRoaming"] = 1
    first.radio_cap()[0]["supportSsidNum"] = 8
    first.components_v2()["system"] = "0.0"

    assert first.device_misc()["supportRoaming"] == 0
    assert second.device_misc()["supportRoaming"] == 0
    assert second.radio_cap()[0]["supportSsidNum"] == 1
    assert second.components_v2()["system"] == "2.0"


def test_device_info_preserves_openwrt_host_metrics_by_default(monkeypatch):
    monkeypatch.setattr(
        "open_omada_device_agent.adapters.outbound.openwrt.device_profile.get_cpu_utilization",
        lambda: 12.5,
    )
    monkeypatch.setattr(
        "open_omada_device_agent.adapters.outbound.openwrt.device_profile.get_memory_utilization",
        lambda: 34.5,
    )

    info = _profile("EAP770", "2.0").device_info()

    assert info["cpuUti"] == 12.5
    assert info["memUti"] == 34.5


def test_device_info_southbound_memory_never_falls_back_to_host(monkeypatch):
    def host_metric_must_not_run():
        raise AssertionError("Host metric used for Netgear")

    monkeypatch.setattr(
        "open_omada_device_agent.adapters.outbound.openwrt.device_profile.get_cpu_utilization",
        host_metric_must_not_run,
    )
    monkeypatch.setattr(
        "open_omada_device_agent.adapters.outbound.openwrt.device_profile.get_memory_utilization",
        host_metric_must_not_run,
    )
    settings = replace(AgentSettings.from_environment(), model="EAP770", model_version="2.0")

    for reported in (39, 0, None):
        profile = GenericOpenWrtAccessPointProfile(
            settings,
            ip_address=lambda: "192.0.2.10",
            capabilities=_TRI_BAND_CAPS,
            uptime_seconds=lambda: 60,
            memory_utilization=lambda: reported,
            include_host_metrics=False,
        )

        info = profile.device_info()

        assert "cpuUti" not in info
        if reported is None:
            assert "memUti" not in info
        else:
            assert info["memUti"] == reported
