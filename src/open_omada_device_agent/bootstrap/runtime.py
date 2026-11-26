"""The sole default wiring point for application ports and concrete adapters."""
from dataclasses import dataclass
from functools import lru_cache, partial
import logging

from ..application.configuration import ApplyDeviceConfiguration
from ..application.contracts import PlatformCapabilities
from ..adapters.outbound.openwrt.bootstrap import OpenWrtBootstrapConfig, OpenWrtStartupBootstrap
from ..adapters.outbound.openwrt.device_commands import OpenWrtClientControlAdapter, SysfsLedAdapter
from ..adapters.outbound.openwrt.uci import OpenWrtUciAdapter
from ..adapters.outbound.openwrt.capabilities import detect_platform_capabilities
from ..adapters.outbound.openwrt.portal_runtime import OpenWrtPortalRuntime
from ..adapters.outbound.openwrt.client_observations import (
    client_stats_payload,
    clients_from_dhcp_leases,
    load_dnsmasq_leases,
    merge_associated_wireless_client_states,
)
from ..network_tools import get_public_ip
from ..adapters.outbound.openwrt.device_profile import GenericOpenWrtAccessPointProfile
from .settings import AgentSettings
from ..projections.inform import InformAssembler, LanObservation
from ..contexts.lifecycle.infrastructure.session_state import JsonSessionStateRepository
from ..adapters.outbound.openwrt.telemetry import collect_openwrt_wireless_clients, collect_openwrt_wireless_inform
from ..adapters.outbound.openwrt.opennds import collect_opennds_clients
from ..adapters.outbound.netgear.uplink import ObservedUplink
from ..adapters.outbound.netgear.beacons import ObservedRadioInform
from ..adapters.outbound.netgear.dashboard import ReadSession, StockDashboard
from ..adapters.outbound.netgear.adapter import netgear_capabilities
from ..adapters.outbound.netgear.platform import LazyNetgearAdapter, NetgearClientSource, NetgearPlatformPort, NetgearWirelessInform
from ..adapters.outbound.netgear.soap import NetgearSoapClient


log = logging.getLogger("open_omada.bootstrap")


@dataclass(frozen=True)
class AgentRuntime:
    configuration: ApplyDeviceConfiguration
    inform: InformAssembler
    state_repository: JsonSessionStateRepository
    settings: AgentSettings
    device_profile: GenericOpenWrtAccessPointProfile
    capabilities: PlatformCapabilities


@lru_cache(maxsize=1)
def build_runtime(settings: AgentSettings) -> AgentRuntime:
    """Build production dependencies; tests may construct the use cases directly."""
    if settings.southbound == "netgear":
        return _build_netgear_runtime(settings)
    capabilities = detect_platform_capabilities(env=dict(settings.capability_environment))
    bootstrap_result = OpenWrtStartupBootstrap(
        config=OpenWrtBootstrapConfig(
            enabled=settings.openwrt_bootstrap,
            ensure_lan=settings.openwrt_bootstrap_lan,
            lan_interface=settings.openwrt_lan_interface,
            lan_bridge=settings.openwrt_lan_bridge,
            lan_ipaddr=settings.openwrt_lan_ipaddr,
            ensure_opennds=settings.openwrt_bootstrap_opennds,
            opennds_gateway_port=settings.opennds_gateway_port,
            opennds_gateway_name=settings.opennds_gateway_name,
            enable_wan_management=settings.openwrt_enable_wan_management,
            wan_zone=settings.openwrt_wan_zone,
        )
    ).apply(capabilities)
    if bootstrap_result.warnings:
        log.warning(
            "OpenWrt bootstrap completed with warning(s): %s",
            "; ".join(bootstrap_result.warnings),
        )
    profile = GenericOpenWrtAccessPointProfile(
        settings,
        ip_address=partial(
            get_public_ip,
            settings.device_ip,
            settings.public_ip_lookup_url,
            settings.public_ip_lookup_timeout,
        ),
        capabilities=capabilities,
    )
    return AgentRuntime(
        configuration=ApplyDeviceConfiguration(
            capability_detector=lambda: capabilities,
            platform_ports=(
                OpenWrtUciAdapter(
                    management_vlan_interface=settings.management_vlan_interface,
                    management_vlan_device=settings.management_vlan_device,
                ),
                OpenWrtPortalRuntime(
                    interface=settings.portal_interface,
                    redirect_port=settings.portal_redirect_port,
                ),
            ),
            command_ports=(
                SysfsLedAdapter(
                    brightness_path=settings.led_brightness_path,
                    trigger_path=settings.led_trigger_path,
                    on_value=settings.led_on_value,
                    off_value=settings.led_off_value,
                    locate_trigger=settings.led_locate_trigger,
                    default_trigger=settings.led_default_trigger,
                ),
                OpenWrtClientControlAdapter(
                    hostapd_iface=settings.hostapd_ubus_iface,
                    block_interface=settings.client_block_interface,
                    rate_limit_interface=settings.client_rate_limit_interface,
                ),
            ),
            allow_ack_only_config=settings.lab_ack_control_plane_config,
        ),
        inform=InformAssembler(
            device_info=profile.device_info,
            lan=LanObservation(settings.lan_rate, settings.lan_duplex, settings.lan_port),
            clients=lambda: merge_associated_wireless_client_states(
                collect_openwrt_wireless_clients(capabilities=capabilities),
                clients_from_dhcp_leases(load_dnsmasq_leases(settings.dhcp_lease_file)),
                collect_opennds_clients(capabilities=capabilities),
            ),
            client_projection=client_stats_payload,
            wireless_projection=lambda: collect_openwrt_wireless_inform(
                capabilities=capabilities
            ),
        ),
        state_repository=JsonSessionStateRepository(
            settings.state_file,
            device_mac=settings.mac,
            controller_host=settings.controller_host,
            device_model=settings.model,
        ),
        settings=settings,
        device_profile=profile,
        capabilities=capabilities,
    )


def _build_netgear_runtime(settings: AgentSettings) -> AgentRuntime:
    """Sidecar wiring: ECSP northbound, Netgear Genie SOAP southbound."""
    if not settings.netgear_host or not settings.netgear_password:
        raise RuntimeError(
            "OMADA_SOUTHBOUND=netgear requires OMADA_NETGEAR_HOST and OMADA_NETGEAR_PASSWORD")
    capabilities = netgear_capabilities()
    adapter = LazyNetgearAdapter(
        NetgearSoapClient(
            settings.netgear_host, settings.netgear_username, settings.netgear_password
        ),
        client_ttl_s=settings.netgear_client_ttl,
        stale_ttl_s=settings.netgear_stale_ttl,
    )
    ssid_ids: dict[tuple[str, str], int] = {}
    bands = ("2.4G",) if settings.model == "EAP110" else ("2.4G", "5G", "6G")
    # LazyNetgearAdapter owns SOAP freshness. Re-evaluate the independent beacon
    # timestamp on each inform so a missed observer update always expires.
    clients = NetgearClientSource(adapter, bands=bands, physical_mac=settings.netgear_physical_mac)
    wireless = NetgearWirelessInform(adapter, ttl_s=0.0, stale_ttl_s=0.0,
                                     bands=bands, ssid_ids=ssid_ids,
                                     station_source=clients.current_stations if settings.netgear_physical_mac is not None else None)
    receivers = [path for path in (settings.netgear_beacon_file, settings.netgear_secondary_beacon_file)
                 if path is not None]
    configured_lan = LanObservation(settings.lan_rate, settings.lan_duplex, settings.lan_port)
    lan = configured_lan
    if settings.netgear_dashboard_cert_sha256:
        session = partial(ReadSession, settings.netgear_host, settings.netgear_dashboard_cert_sha256,
                          settings.netgear_username, settings.netgear_password)
        dashboard = StockDashboard(session, settings.netgear_dashboard_uplink)

        def actual_channels():
            snapshot = dashboard.latest()
            return snapshot.channels if snapshot else {}

        def measured_lan():
            snapshot = dashboard.latest()
            if snapshot is None or snapshot.uplink is None:
                return configured_lan
            observed = snapshot.uplink
            duplex = 2 if observed.full_duplex else 1 if observed.full_duplex is False else 0
            return LanObservation(float(observed.mbps), duplex, configured_lan.port, observed.up)

        lan = measured_lan
        wireless = ObservedRadioInform(wireless, *receivers, panel_channels=actual_channels)
    elif receivers:
        wireless = ObservedRadioInform(wireless, *receivers)
    port = NetgearPlatformPort(adapter, ssid_ids=ssid_ids)
    profile = GenericOpenWrtAccessPointProfile(
        settings,
        ip_address=partial(
            get_public_ip,
            settings.device_ip,
            settings.public_ip_lookup_url,
            settings.public_ip_lookup_timeout,
        ),
        capabilities=capabilities,
        uptime_seconds=adapter.read_uptime,
        memory_utilization=adapter.read_used_memory_percent,
        include_host_metrics=False,
    )
    log.warning("Netgear southbound active: host=%s (single main SSID, no VLAN/portal)",
                settings.netgear_host)
    return AgentRuntime(
        configuration=ApplyDeviceConfiguration(
            capability_detector=lambda: capabilities,
            platform_ports=(port,),
            command_ports=(port,),
            allow_ack_only_config=settings.lab_ack_control_plane_config,
        ),
        inform=InformAssembler(
            device_info=profile.device_info,
            lan=lan,
            clients=clients,
            client_projection=client_stats_payload,
            wireless_projection=wireless,
            uplink_traffic=(ObservedUplink(settings.netgear_uplink_file, settings.netgear_host)
                            if settings.netgear_uplink_file else None),
        ),
        state_repository=JsonSessionStateRepository(
            settings.state_file,
            device_mac=settings.mac,
            controller_host=settings.controller_host,
            device_model=settings.model,
        ),
        settings=settings,
        device_profile=profile,
        capabilities=capabilities,
    )
