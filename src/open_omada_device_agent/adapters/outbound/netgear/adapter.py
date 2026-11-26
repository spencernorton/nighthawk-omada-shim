"""Netgear southbound adapter: maps the shim's single-AP intent onto the
RS700's fixed main/guest/IoT WLAN structure via Genie SOAP.

Deliberate limits (see plan): only the main SSID is configurable; additional
WLANs, per-SSID VLANs, portal and enterprise auth are rejected, never
silently dropped, so Omada can never show a fake-applied configuration.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ....application.contracts import PlatformCapabilities
from ....contexts.wireless.domain import RadioBand
from .soap import AttachedClient, BandState, NetgearSoapClient, SystemInfo

log = logging.getLogger("open_omada.netgear.adapter")

BANDS = ("2.4G", "5G", "6G")


def netgear_capabilities() -> PlatformCapabilities:
    return PlatformCapabilities(
        platform="netgear-soap",
        radio_bands=(RadioBand.TWO_G, RadioBand.FIVE_G, RadioBand.SIX_G),
        max_ssids=1,
        supports_wlan_config=True,
        supports_wpa2_psk=True,
        supports_wpa3_psk=True,
        supports_wpa_enterprise=False,
        supports_radius=False,
        supports_ssid_vlan=False,
        supports_dynamic_vlan=False,
        supports_management_vlan=False,
        supports_portal=False,
        supports_dhcp_tracking=True,
        supports_option82=False,
        supports_led_control=False,
        supports_client_operations=False,
        supports_client_rate_limits=False,
    )


@dataclass(frozen=True)
class DesiredMainWlan:
    ssid: str | None = None  # None = leave SSID/PSK untouched (radio-only update)
    passphrase: str | None = None
    channels: tuple[tuple[str, str], ...] = ()  # (band, channel)


@dataclass(frozen=True)
class NetgearReconcileResult:
    applied: bool
    changed: bool
    error: str = ""
    calls: int = 0


def _same_channel(current: str, desired: str) -> bool:
    try:
        return int(current) == int(desired)
    except (TypeError, ValueError):
        return str(current) == str(desired)


class NetgearAdapter:
    def __init__(self, client: NetgearSoapClient) -> None:
        self._client = client

    def current_psk(self, band: str) -> str:
        return self._client.current_psk(band)

    def read_state(self) -> dict[str, BandState]:
        return {band: self._client.band_state(band) for band in BANDS}

    def read_uptime(self) -> int | None:
        reader = getattr(self._client, "sys_uptime_seconds", None)
        if reader is None:
            return None
        try:
            return reader()
        except Exception as exc:
            log.warning("netgear sys_uptime failed: %s", exc)
            return None

    def read_system_info(self) -> SystemInfo | None:
        reader = getattr(self._client, "system_info", None)
        if reader is None:
            return None
        try:
            return reader()
        except Exception as exc:
            log.warning("netgear system info failed: %s", exc)
            return None

    def read_used_memory_percent(self) -> int | None:
        info = self.read_system_info()
        return info.used_memory_percent if info is not None else None

    def read_clients(self) -> list[AttachedClient]:
        # Prefer GetAttachDevice2 (band/SSID per client); older firmware
        # or a failed detailed call falls back to the v1 list.
        detailed = getattr(self._client, "attached_clients_detailed", None)
        if detailed is not None:
            try:
                return detailed()
            except Exception as exc:
                log.warning("netgear detailed clients failed, using v1: %s", exc)
        return self._client.attached_clients()

    def reconcile(self, desired: DesiredMainWlan) -> NetgearReconcileResult:
        """Apply supported main-SSID intent and surface unsupported operations.

        An unsupported operation is a soft error here so supported operations
        can still be applied; the application layer rejects the overall result.
        """
        if desired.ssid is None and desired.passphrase is not None:
            return NetgearReconcileResult(
                applied=False,
                changed=False,
                error="passphrase rotation requires an SSID",
            )
        calls = 0
        unsupported: list[str] = []
        try:
            state = self.read_state()
            for band in BANDS:
                current = state[band]
                if desired.ssid is None:
                    break
                if current.ssid != desired.ssid and not desired.passphrase:
                    # SSID rename and PSK rotate travel together in the
                    # Netgear setter; a rename without a passphrase cannot
                    # be applied honestly.
                    return NetgearReconcileResult(
                        applied=False, changed=False,
                        error="ssid rename requires a passphrase", calls=calls)
                if desired.passphrase:
                    # Skip the setter when name+key already match: the
                    # Netgear PSK setter is unreliable (live RS700 returns
                    # 402; pynetgear leaves it unimplemented), so only a
                    # genuine rotation should ever invoke it.
                    if (current.ssid == desired.ssid
                            and self.current_psk(band) == desired.passphrase):
                        continue
                    self._client.set_psk(band, desired.ssid, desired.passphrase)
                    calls += 1
            for band, channel in desired.channels:
                if channel.casefold() == "auto":
                    current_channel = state[band].channel.strip().casefold()
                    if current_channel in {"0", "auto"}:
                        continue
                    # Netgear SOAP SetChannel accepts numeric channels only
                    # (live RS700: "Auto"/"0" -> ResponseCode=402).
                    message = f"channel Auto on {band} unsupported on netgear"
                    unsupported.append(message)
                    log.warning("netgear: %s; leaving router channel unchanged", message)
                    continue
                if _same_channel(state[band].channel, channel):
                    continue
                self._client.set_channel(band, channel)
                calls += 1
        except Exception as exc:  # surfaced, never swallowed as success
            log.error("netgear reconcile failed: %s", exc)
            return NetgearReconcileResult(
                applied=False,
                changed=calls > 0,
                error="; ".join((*unsupported, str(exc))),
                calls=calls,
            )
        return NetgearReconcileResult(
            applied=True,
            changed=calls > 0,
            error="; ".join(unsupported),
            calls=calls,
        )
