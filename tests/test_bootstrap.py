from dataclasses import replace

import pytest

from open_omada_device_agent.bootstrap import AgentSettings, build_runtime
from open_omada_device_agent.contexts.lifecycle.domain import ManagedState


def test_runtime_uses_injected_settings_for_profile_and_repository(tmp_path):
    settings = replace(
        AgentSettings.from_environment(),
        controller_host="controller.example.test",
        mac="02:00:00:00:12:34",
        device_name="injected-ap",
        state_file=tmp_path / "managed.json",
    )

    runtime = build_runtime(settings)
    identity = runtime.device_profile.identity()
    state = ManagedState(
        version=1,
        mac=identity.mac.value,
        controller_host=settings.controller_host,
        controller_id="controller-id",
        manage_port=settings.manage_port,
    )
    runtime.state_repository.save(state)

    assert identity.name == "injected-ap"
    assert runtime.settings is settings
    assert runtime.state_repository.load() == state


def test_repository_rejects_state_for_a_different_runtime_identity(tmp_path):
    settings = replace(
        AgentSettings.from_environment(),
        controller_host="controller.example.test",
        state_file=tmp_path / "managed.json",
    )
    runtime = build_runtime(settings)
    foreign = ManagedState(
        version=1,
        mac="02:00:00:00:ff:ff",
        controller_host=settings.controller_host,
        controller_id="controller-id",
        manage_port=settings.manage_port,
    )

    try:
        runtime.state_repository.save(foreign)
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("repository accepted state for another device")


def test_settings_repr_redacts_device_password():
    settings = replace(
        AgentSettings.from_environment(),
        device_password="do-not-log-" + "this-secret",
    )

    assert ("do-not-log-" + "this-secret") not in repr(settings)


def test_capabilities_use_bootstrap_snapshot_not_later_environment(monkeypatch):
    settings = replace(
        AgentSettings.from_environment(),
        capability_environment=(("OMADA_PLATFORM", "generic"),),
    )
    monkeypatch.setenv("OMADA_PLATFORM", "openwrt")

    runtime = build_runtime(settings)

    assert runtime.capabilities.platform == "generic"


def test_netgear_runtime_uses_one_stale_window_and_eap110_single_band_clients(tmp_path):
    settings = replace(
        AgentSettings.from_environment(),
        southbound="netgear",
        netgear_host="router.example.test",
        netgear_password="test-only-password",
        netgear_stale_ttl=47.0,
        model="EAP110",
        state_file=tmp_path / "netgear-managed.json",
    )

    runtime = build_runtime(settings)

    wireless = runtime.inform._wireless_projection
    clients = runtime.inform._clients
    assert wireless._ttl_s == 0.0
    assert wireless._stale_ttl_s == 0.0
    assert wireless._adapter._stale_ttl_s == 47.0
    assert wireless._bands == ("2.4G",)
    assert clients._bands == ("2.4G",)


def test_netgear_runtime_uses_cached_router_memory_without_host_metrics(
    tmp_path, monkeypatch
):
    from open_omada_device_agent.adapters.outbound.netgear.soap import SystemInfo

    calls = {"login": 0, "system_info": 0}

    class Client:
        def __init__(self, *args):
            pass

        def login(self):
            calls["login"] += 1

        def system_info(self):
            calls["system_info"] += 1
            return SystemInfo(load_average_x100=164, free_memory_percent=61)

        def sys_uptime_seconds(self):
            return 60

    def host_metric_must_not_run():
        raise AssertionError("Host metric used for Netgear")

    monkeypatch.setattr(
        "open_omada_device_agent.bootstrap.runtime.NetgearSoapClient", Client
    )
    monkeypatch.setattr(
        "open_omada_device_agent.adapters.outbound.openwrt.device_profile.get_cpu_utilization",
        host_metric_must_not_run,
    )
    monkeypatch.setattr(
        "open_omada_device_agent.adapters.outbound.openwrt.device_profile.get_memory_utilization",
        host_metric_must_not_run,
    )
    settings = replace(
        AgentSettings.from_environment(),
        southbound="netgear",
        netgear_host="router.example.test",
        netgear_password="test-only-password",
        model="EAP770",
        state_file=tmp_path / "netgear-system-info-managed.json",
    )
    runtime = build_runtime(settings)

    first = runtime.device_profile.device_info()
    second = runtime.device_profile.device_info()

    for info in (first, second):
        assert info["memUti"] == 39
        assert "cpuUti" not in info
        assert info["upTime"] == "0 days 00:01:00"
    assert calls == {"login": 1, "system_info": 1}


def test_netgear_runtime_stale_wireless_data_expires_at_configured_age(
    tmp_path, monkeypatch
):
    from open_omada_device_agent.adapters.outbound.netgear.soap import BandState

    clock = [100.0]
    fail = [False]
    bands = {
        band: BandState(
            band=band,
            ssid="ExampleNet",
            enabled=True,
            broadcast=True,
            channel="1",
            wireless_mode="688Mbps",
            security="WPA2-PSK",
            mac=f"02:00:00:00:00:0{index}",
        )
        for index, band in enumerate(("2.4G", "5G", "6G"), start=1)
    }

    class FlakyClient:
        def __init__(self, *args):
            pass

        def login(self):
            pass

        def band_state(self, band):
            if fail[0]:
                raise RuntimeError("state unavailable")
            return bands[band]

        def attached_clients_detailed(self):
            if fail[0]:
                raise RuntimeError("clients unavailable")
            return []

        def attached_clients(self):
            if fail[0]:
                raise RuntimeError("clients unavailable")
            return []

    monkeypatch.setattr(
        "open_omada_device_agent.bootstrap.runtime.NetgearSoapClient", FlakyClient
    )
    settings = replace(
        AgentSettings.from_environment(),
        southbound="netgear",
        netgear_host="router.example.test",
        netgear_password="test-only-password",
        netgear_client_ttl=5.0,
        netgear_stale_ttl=40.0,
        model="EAP770",
        state_file=tmp_path / "netgear-stale-managed.json",
    )
    runtime = build_runtime(settings)
    wireless = runtime.inform._wireless_projection
    adapter = wireless._adapter
    adapter._now = lambda: clock[0]
    wireless._now = lambda: clock[0]

    initial = wireless()
    assert initial

    clock[0] += 31.0
    fail[0] = True
    assert wireless() == initial
    clock[0] += 8.0
    assert wireless() == initial
    clock[0] += 1.0
    assert wireless() == {}


def test_settings_reject_invalid_opennds_gateway_port():
    settings = replace(
        AgentSettings.from_environment(),
        controller_host="controller.example.test",
        opennds_gateway_port=70000,
    )

    with pytest.raises(RuntimeError, match="OMADA_OPENNDS_GATEWAY_PORT"):
        settings.validate()


def test_settings_reject_missing_openwrt_lan_target():
    settings = replace(
        AgentSettings.from_environment(),
        controller_host="controller.example.test",
        openwrt_lan_bridge="",
    )

    with pytest.raises(RuntimeError, match="OMADA_OPENWRT_LAN_INTERFACE"):
        settings.validate()
