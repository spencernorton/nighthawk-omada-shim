"""Immutable runtime settings consumed through application services."""
from dataclasses import dataclass, field
from pathlib import Path
import re

from ..util.mac_format import unicast_mac


@dataclass(frozen=True)
class AgentSettings:
    controller_host: str
    discovery_port: int
    manage_port: int
    local_discovery_port: int
    discovery_interval: float
    tcp_timeout: float
    inform_interval: float
    reconnect_delay: float
    managed_reconnect_attempts: int
    tls_verify: bool
    tls_ca_file: Path | None
    mac: str
    device_name: str
    model: str
    model_version: str
    hardware_version: str
    firmware_version: str
    customize_region: int
    device_ip: str
    public_ip_lookup_url: str
    public_ip_lookup_timeout: float
    lan_rate: float
    lan_duplex: int
    lan_port: str
    dhcp_lease_file: Path
    led_brightness_path: str
    led_on_value: str
    led_off_value: str
    led_trigger_path: str
    led_locate_trigger: str
    led_default_trigger: str
    hostapd_ubus_iface: str
    client_block_interface: str
    client_rate_limit_interface: str
    portal_interface: str
    portal_redirect_port: int
    management_vlan_interface: str
    management_vlan_device: str
    openwrt_bootstrap: bool
    openwrt_bootstrap_lan: bool
    openwrt_lan_interface: str
    openwrt_lan_bridge: str
    openwrt_lan_ipaddr: str
    openwrt_bootstrap_opennds: bool
    opennds_gateway_port: int
    opennds_gateway_name: str
    openwrt_enable_wan_management: bool
    openwrt_wan_zone: str
    lab_ack_control_plane_config: bool
    ecsp_version: str
    ecsp_ver_cap: int
    controller_id: str
    destination_controller_id: str
    site_id: str
    device_username: str
    device_password: str = field(repr=False)
    device_cipher_type: int
    state_file: Path
    capability_environment: tuple[tuple[str, str], ...]
    southbound: str = "openwrt"
    netgear_host: str = ""
    netgear_username: str = "admin"
    netgear_password: str = field(default="", repr=False)
    netgear_client_ttl: float = 30.0
    netgear_stale_ttl: float = 180.0
    heartbeat_file: Path | None = None
    netgear_beacon_file: Path | None = None
    netgear_uplink_file: Path | None = None
    netgear_secondary_beacon_file: Path | None = None
    netgear_dashboard_cert_sha256: str = ""
    netgear_dashboard_uplink: str = "WAN"
    netgear_physical_mac: str | None = None

    def validate(self) -> None:
        if not self.controller_host:
            raise RuntimeError("OMADA_CONTROLLER_HOST is required")
        if not (1 <= self.discovery_port <= 65535 and 1 <= self.manage_port <= 65535):
            raise RuntimeError("OMADA discovery/manage ports must be between 1 and 65535")
        if self.openwrt_bootstrap and not (1 <= self.opennds_gateway_port <= 65535):
            raise RuntimeError("OMADA_OPENNDS_GATEWAY_PORT must be between 1 and 65535")
        if self.openwrt_bootstrap_lan and (
            not self.openwrt_lan_interface or not self.openwrt_lan_bridge
        ):
            raise RuntimeError(
                "OMADA_OPENWRT_LAN_INTERFACE and OMADA_OPENWRT_LAN_BRIDGE are required"
            )
        if self.openwrt_enable_wan_management and not self.openwrt_wan_zone:
            raise RuntimeError("OMADA_OPENWRT_WAN_ZONE is required")
        if self.netgear_physical_mac is not None and unicast_mac(self.netgear_physical_mac) is None:
            raise RuntimeError("OMADA_NETGEAR_PHYSICAL_MAC must be a valid unicast hardware MAC")
        if self.netgear_client_ttl < 0:
            raise RuntimeError("OMADA_NETGEAR_CLIENT_TTL must be >= 0")
        if self.netgear_stale_ttl < 0:
            raise RuntimeError("OMADA_NETGEAR_STALE_TTL must be >= 0")
        if self.netgear_dashboard_cert_sha256 and not re.fullmatch(
            r"[0-9A-Fa-f]{64}", self.netgear_dashboard_cert_sha256
        ):
            raise RuntimeError("OMADA_NETGEAR_DASHBOARD_CERT_SHA256 requires a 64-digit hex fingerprint")
        if self.tls_ca_file is not None and not self.tls_ca_file.exists():
            raise RuntimeError(f"OMADA_TLS_CA_FILE does not exist: {self.tls_ca_file}")
