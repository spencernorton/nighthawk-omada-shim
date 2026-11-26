"""Netgear platform port + client telemetry source for the agent runtime.

Reconcile honours only what the RS700 can really do (single main SSID,
per-band PSK/channel). Anything else in a controller SET_REQUEST is
rejected so Omada never displays a fake-applied configuration.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from ....util.mac_format import to_omada, unicast_mac
from ....application.commands import ApplyDeviceConfigurationCommand
from ....application.configuration import ApplyConfigurationResult
from ....application.contracts import PlatformCapabilities
from ....contexts.clients.domain import ClientRadioBand, WirelessClientState
from ....contexts.wireless.domain import RadioBand, RadioConfig, WirelessNetwork
from ....shared.domain import MacAddress
from .adapter import DesiredMainWlan, NetgearAdapter
from .soap import AttachedClient, NetgearSoapClient, SystemInfo, parse_wireless_mode_mbps

log = logging.getLogger("open_omada.netgear.platform")

_CLIENT_BANDS = {"2.4G": ClientRadioBand.TWO_G, "5G": ClientRadioBand.FIVE_G, "6G": ClientRadioBand.SIX_G}
_BAND_NAME = {RadioBand.TWO_G: "2.4G", RadioBand.FIVE_G: "5G", RadioBand.SIX_G: "6G"}


def _radio_errors(radio: RadioConfig) -> list[str]:
    errors = []
    if radio.channel_width not in (None, 0):
        errors.append(f"chanWidth={radio.channel_width} on {radio.band.value} unsupported on netgear")
    if radio.tx_power not in (None, 0):
        errors.append(f"txPower={radio.tx_power} on {radio.band.value} unsupported on netgear")
    if radio.channel_limit:
        errors.append(f"channelLimit=True on {radio.band.value} unsupported on netgear")
    if radio.wireless_mode not in (None, 0):
        errors.append(f"wirelessMode={radio.wireless_mode} on {radio.band.value} unsupported on netgear")
    return errors


def _wlan_errors(wlan: WirelessNetwork) -> list[str]:
    errors = []
    label = f"for {wlan.name!r} on {wlan.band.value}"
    if wlan.operation not in (None, 1):
        errors.append(f"WLAN operation={wlan.operation} {label} unsupported on netgear")
    if wlan.client_isolation:
        errors.append(f"ssidIsolation=True {label} unsupported on netgear")
    if wlan.vlan.vlan_id not in (None, 0):
        errors.append(f"ssid vlan {wlan.vlan.vlan_id} unsupported on netgear")
    if wlan.vlan.dynamic_vlan_mode not in (None, 0):
        errors.append(
            f"dynamic VLAN mode={wlan.vlan.dynamic_vlan_mode} {label} unsupported on netgear"
        )
    if wlan.vlan.vlan_pool_ids:
        errors.append(f"VLAN pools {label} unsupported on netgear")
    if wlan.vlan.dhcp_option82 is not None and wlan.vlan.dhcp_option82.enabled:
        errors.append(f"DHCP Option 82 enabled {label} unsupported on netgear")
    if wlan.portal.enabled:
        errors.append("captive portal unsupported on netgear")
    security = wlan.security
    if (
        security.radius_profile_id
        or security.radius_auth
        or security.radius_accounting
        or security.radius_mac_auth
    ):
        errors.append("wpa enterprise unsupported on netgear")
    if security.security_mode not in (None, 0, 3):
        errors.append(f"securityMode={security.security_mode} {label} unsupported on netgear")
    if security.security_mode == 0 and security.psk_key is not None:
        errors.append(f"pskKey with securityMode=0 {label} unsupported on netgear")
    for field_name, value in (
        ("authType", security.auth_type),
        ("wpaVer", security.wpa_version),
        ("wpaCipher", security.wpa_cipher),
        ("pmfMode", security.pmf_mode),
    ):
        if value not in (None, 0):
            errors.append(f"{field_name}={value} {label} unsupported on netgear")
    if security.psk_version not in (None, 0, 3):
        errors.append(f"pskVer={security.psk_version} {label} unsupported on netgear")
    if security.psk_cipher not in (None, 0, 1):
        errors.append(f"pskCipher={security.psk_cipher} {label} unsupported on netgear")
    if security.fast_roaming:
        errors.append(f"fastTransition.enable11r=True {label} unsupported on netgear")
    return errors


def _command_errors(update: ApplyDeviceConfigurationCommand) -> list[str]:
    errors = []
    if update.led is not None:
        if update.led.enabled is False:
            errors.append("led.enable=False unsupported on netgear")
        if update.led.locate:
            errors.append("led.locate=True unsupported on netgear")
    if update.wifi_control_led is not None:
        if update.wifi_control_led.enabled is False:
            errors.append("wifiControlLed.enable=False unsupported on netgear")
        if update.wifi_control_led.is_pressed:
            errors.append("wifiControlLed.isPressed=True unsupported on netgear")
    return errors


class NetgearPlatformPort:
    def __init__(
        self,
        adapter: NetgearAdapter,
        *,
        ssid_ids: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self._adapter = adapter
        self._ssid_ids = ssid_ids if ssid_ids is not None else {}

    def reconcile(
        self,
        update: ApplyDeviceConfigurationCommand,
        capabilities: PlatformCapabilities,
    ) -> ApplyConfigurationResult:
        mv = update.management_vlan
        if mv is not None and mv.enabled and mv.vlan_id not in (None, 0, 1):
            return ApplyConfigurationResult(False, error="management vlan unsupported on netgear")
        if update.portal_configs:
            return ApplyConfigurationResult(False, error="captive portal unsupported on netgear")
        if update.client_configs or update.client_operations or update.client_rate_config is not None:
            return ApplyConfigurationResult(False, error="client operations unsupported on netgear")

        errors = _command_errors(update)
        policy = update.portal_free_policy
        portal_requested = any(wlan.portal.enabled for wlan in update.wlans)
        if (
            portal_requested
            and policy is not None
            and (policy.layer2_rules or policy.url_rules)
        ):
            errors.append("portalFreePolicyConfig with rules unsupported on netgear")

        requested_names = {w.name for w in update.wlans}
        if len(requested_names) > 1:
            return ApplyConfigurationResult(
                False, error=f"netgear supports one main SSID, got {sorted(requested_names)}")

        radio_checks = [(radio, _radio_errors(radio)) for radio in update.radios]
        wlan_checks = [(wlan, _wlan_errors(wlan)) for wlan in update.wlans]
        for radio, radio_errors in radio_checks:
            if radio.band not in _BAND_NAME:
                radio_errors.append(f"radio band {radio.band.value} unsupported on netgear")
        for wlan, wlan_errors in wlan_checks:
            if wlan.band not in _BAND_NAME:
                wlan_errors.append(f"SSID band {wlan.band.value} unsupported on netgear")

        needs_state = any(
            radio.enabled is not None and radio.band in _BAND_NAME
            for radio in update.radios
        ) or any(
            wlan.band in _BAND_NAME
            and (
                wlan.broadcast is not None
                or wlan.security.security_mode == 0
                or (wlan.security.security_mode == 3 and wlan.security.psk_key is None)
            )
            for wlan in update.wlans
        )
        state = None
        if needs_state:
            try:
                state = self._adapter.read_state()
            except Exception as exc:
                errors.extend(
                    error
                    for _, check_errors in (*radio_checks, *wlan_checks)
                    for error in check_errors
                )
                errors.append(f"cannot verify Netgear current state: {exc}")
                return ApplyConfigurationResult(False, error="; ".join(errors))

        for radio, radio_errors in radio_checks:
            if (
                state is not None
                and radio.enabled is not None
                and radio.band in _BAND_NAME
                and state[_BAND_NAME[radio.band]].enabled != radio.enabled
            ):
                radio_errors.append(
                    f"radioEnable={radio.enabled} on {radio.band.value} unsupported on netgear"
                )
        configurable_wlans = []
        for wlan, wlan_errors in wlan_checks:
            if (
                state is not None
                and wlan.broadcast is not None
                and wlan.band in _BAND_NAME
                and state[_BAND_NAME[wlan.band]].broadcast != wlan.broadcast
            ):
                wlan_errors.append(
                    f"ssidBcast={wlan.broadcast} for {wlan.name!r} "
                    f"on {wlan.band.value} unsupported on netgear"
                )
            security_mode = wlan.security.security_mode
            if (
                state is not None
                and wlan.band in _BAND_NAME
                and (
                    security_mode == 0
                    or (security_mode == 3 and wlan.security.psk_key is None)
                )
            ):
                current_security = state[_BAND_NAME[wlan.band]].security.strip().casefold()
                current_is_open = current_security in {"none", "open"}
                current_is_psk = (
                    "wpa" in current_security
                    and "enterprise" not in current_security
                    and "radius" not in current_security
                )
                if (security_mode == 0 and not current_is_open) or (
                    security_mode == 3 and not current_is_psk
                ):
                    wlan_errors.append(
                        f"securityMode={security_mode} for {wlan.name!r} "
                        f"on {wlan.band.value} unsupported on netgear"
                    )
            if not wlan_errors:
                configurable_wlans.append(wlan)

        if any(wlan_errors for _, wlan_errors in wlan_checks):
            # Netgear's SSID/PSK setter writes every band, including rejected ones.
            configurable_wlans = []

        errors.extend(error for _, check_errors in radio_checks for error in check_errors)
        errors.extend(error for _, check_errors in wlan_checks for error in check_errors)
        names = {wlan.name for wlan in configurable_wlans}
        ssid = next(iter(names)) if names else None
        psk = None
        for wlan in configurable_wlans:
            if wlan.security.psk_key is not None:
                psk = wlan.security.psk_key.reveal()
        channels = tuple(
            (_BAND_NAME[radio.band], "Auto" if not radio.channel else str(radio.channel))
            for radio in update.radios
            if radio.band in _BAND_NAME and radio.channel is not None
        )
        if ssid is None and not channels:
            return ApplyConfigurationResult(not errors, changed=False, error="; ".join(errors))

        result = self._adapter.reconcile(
            DesiredMainWlan(ssid=ssid, passphrase=psk, channels=channels))
        if result.applied:
            for wlan in configurable_wlans:
                if wlan.ssid_id is not None and wlan.band in _BAND_NAME:
                    self._ssid_ids[(_BAND_NAME[wlan.band], wlan.name)] = int(wlan.ssid_id)
        error = "; ".join((*errors, result.error)) if result.error else "; ".join(errors)
        return ApplyConfigurationResult(result.applied and not error, result.changed, error)


class LazyNetgearAdapter(NetgearAdapter):
    """Logs in on first use, caches SOAP reads, and serves bounded stale state on transient errors."""

    def __init__(
        self,
        client: NetgearSoapClient,
        *,
        client_ttl_s: float = 30.0,
        state_ttl_s: float = 30.0,
        stale_ttl_s: float = 180.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(client)
        self._client_ref = client
        self._logged_in = False
        self._client_ttl_s = max(0.0, float(client_ttl_s))
        self._state_ttl_s = max(0.0, float(state_ttl_s))
        self._stale_ttl_s = max(0.0, float(stale_ttl_s))
        self._now = now
        self._lock = threading.RLock()
        self._cached_state: dict | None = None
        self._state_ts = 0.0
        self._cached_clients: list | None = None
        self._clients_ts = 0.0
        self._cached_uptime: int | None = None
        self._uptime_ts = 0.0
        self._cached_system_info: SystemInfo | None = None
        self._system_info_ts = 0.0

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self._client_ref.login()
            self._logged_in = True

    def read_state(self):  # type: ignore[override]
        with self._lock:
            now = self._now()
            if self._state_ttl_s > 0.0 and self._cached_state is not None:
                if (now - self._state_ts) < self._state_ttl_s:
                    return dict(self._cached_state)
            try:
                self._ensure_login()
                fresh = super().read_state()
            except Exception as exc:
                age = self._now() - self._state_ts
                if self._cached_state is not None and self._stale_ttl_s > 0.0 and age < self._stale_ttl_s:
                    log.warning(
                        "netgear state poll failed (%s); serving cached state (age=%.1fs)",
                        exc,
                        age,
                    )
                    return dict(self._cached_state)
                raise
            if self._state_ttl_s > 0.0 or self._stale_ttl_s > 0.0:
                self._cached_state = dict(fresh)
                self._state_ts = self._now()
            return fresh

    def read_clients(self):
        return self.read_clients_with_age()[0]

    def read_clients_with_age(self) -> tuple[list[AttachedClient], float]:
        """Return observations and their age since the last successful SOAP read."""
        with self._lock:
            now = self._now()
            if self._client_ttl_s > 0.0 and self._cached_clients is not None:
                if (now - self._clients_ts) < self._client_ttl_s:
                    return list(self._cached_clients), max(0.0, now - self._clients_ts)
            try:
                self._ensure_login()
                fresh = super().read_clients()
            except Exception as exc:
                age = self._now() - self._clients_ts
                if self._cached_clients is not None and self._stale_ttl_s > 0.0 and age < self._stale_ttl_s:
                    log.warning(
                        "netgear client poll failed (%s); serving cached clients (age=%.1fs)",
                        exc,
                        age,
                    )
                    return list(self._cached_clients), max(0.0, age)
                raise
            if self._client_ttl_s > 0.0 or self._stale_ttl_s > 0.0:
                self._cached_clients = list(fresh)
                self._clients_ts = self._now()
            return fresh, 0.0

    def read_uptime(self) -> int | None:
        with self._lock:
            reader = getattr(self._client_ref, "sys_uptime_seconds", None)
            if reader is None:
                return None
            now = self._now()
            if self._state_ttl_s > 0.0 and self._cached_uptime is not None:
                elapsed = max(0.0, now - self._uptime_ts)
                if elapsed < self._state_ttl_s:
                    return self._cached_uptime + int(elapsed)
            try:
                self._ensure_login()
                fresh = reader()
            except Exception as exc:
                age = max(0.0, self._now() - self._uptime_ts)
                if self._cached_uptime is not None and self._stale_ttl_s > 0.0 and age < self._stale_ttl_s:
                    log.warning(
                        "netgear uptime poll failed (%s); serving cached uptime (age=%.1fs)",
                        exc,
                        age,
                    )
                    return self._cached_uptime + int(age)
                log.warning("netgear uptime poll failed: %s", exc)
                return None
            if fresh is not None:
                self._cached_uptime = int(fresh)
                self._uptime_ts = self._now()
            return fresh

    def read_system_info(self) -> SystemInfo | None:
        with self._lock:
            reader = getattr(self._client_ref, "system_info", None)
            if reader is None:
                return None
            now = self._now()
            if self._state_ttl_s > 0.0 and self._cached_system_info is not None:
                if (now - self._system_info_ts) < self._state_ttl_s:
                    return self._cached_system_info
            try:
                self._ensure_login()
                fresh = reader()
            except Exception as exc:
                age = max(0.0, self._now() - self._system_info_ts)
                if (
                    self._cached_system_info is not None
                    and self._stale_ttl_s > 0.0
                    and age < self._stale_ttl_s
                ):
                    log.warning(
                        "netgear system info poll failed (%s); serving cached metrics (age=%.1fs)",
                        exc,
                        age,
                    )
                    return self._cached_system_info
                log.warning("netgear system info poll failed: %s", exc)
                return None
            if fresh is not None and (self._state_ttl_s > 0.0 or self._stale_ttl_s > 0.0):
                self._cached_system_info = fresh
                self._system_info_ts = self._now()
            return fresh

    def reconcile(self, desired: DesiredMainWlan):  # type: ignore[override]
        with self._lock:
            self._cached_state = None
            self._ensure_login()
            result = super().reconcile(desired)
            if result.changed:
                self._cached_state = None
            return result


def _normalize_channel(raw: str | None) -> str:
    if raw is None or raw == "":
        return ""
    text = str(raw).strip()
    if text.casefold() == "auto":
        return "0"
    if text.isdigit():
        return str(int(text))
    return text


def _bandwidth_for_band(band: str, mbps: int | None) -> str:
    if band == "2.4G":
        return "20MHz" if (mbps is not None and mbps < 300) else "40MHz"
    if band == "5G":
        return "80MHz" if (mbps is not None and mbps < 2000) else "160MHz"
    if band == "6G":
        return "320MHz" if (mbps is not None and mbps >= 8000) else "160MHz"
    return "20MHz"


class NetgearWirelessInform:
    """Per-band wSettings and ssidStats for Omada 6.3 ApWlanInformData (j.class).

    Exact Controller 6.3 decoder contracts verified against manager-device:
    * ``txR`` requires a decimal point (``"<int>.0Mbps"``);
    * ``txPower`` requires a 3-char suffix (``"<int>dBm"``);
    * ``txUti``/``rxUti``/``interUti``/``busyUti`` must be ints (prevents health NPE);
    * ``ssidStats`` entries require integer ``id`` (prevents monitor-statistic NPE).
    """

    def __init__(
        self,
        adapter: NetgearAdapter,
        *,
        ttl_s: float = 60.0,
        stale_ttl_s: float = 180.0,
        bands: tuple[str, ...] = ("2.4G", "5G", "6G"),
        ssid_ids: dict[tuple[str, str], int] | None = None,
        station_source: Callable[[], tuple[WirelessClientState, ...]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._adapter = adapter
        self._station_source = station_source
        self._ttl_s = ttl_s
        self._stale_ttl_s = max(0.0, float(stale_ttl_s))
        self._bands = bands
        self._ssid_ids = ssid_ids if ssid_ids is not None else {}
        self._now = now
        self._cached: dict[str, object] = {}
        self._cached_ids_snapshot: dict[tuple[str, str], int] = {}
        self._ts = 0.0

    def __call__(self) -> dict[str, object]:
        ts = self._now()
        ids_now = dict(self._ssid_ids)
        if (self._station_source is None and self._cached and ts - self._ts < self._ttl_s
                and ids_now == self._cached_ids_snapshot):
            return self._cached
        try:
            state = self._adapter.read_state()
            stations = self._station_source() if self._station_source is not None else None
            clients = self._adapter.read_clients() if stations is None else []
            single_band_v1 = len(self._bands) == 1 and not any(
                c.band for c in clients if c.connection == "wireless"
            )
            suffixes = {"2.4G": "2G", "5G": "5G", "6G": "6G"}
            payload: dict[str, object] = {}
            for band in self._bands:
                suffix = suffixes[band]
                info = state[band]
                mbps = parse_wireless_mode_mbps(info.wireless_mode)
                if stations is not None:
                    local = [station for station in stations if station.radio == _CLIENT_BANDS[band]]
                    band_sta_num = len(local)
                    count = sum(station.ssid == info.ssid for station in local)
                elif single_band_v1:
                    band_sta_num = sum(
                        1 for c in clients if c.connection == "wireless"
                    )
                    count = band_sta_num
                else:
                    band_sta_num = sum(
                        1 for c in clients if c.connection == "wireless" and c.band == band
                    )
                    count = sum(
                        1
                        for c in clients
                        if c.connection == "wireless"
                        and c.band == band
                        and c.ssid
                        and c.ssid == info.ssid
                    )
                w_settings: dict[str, object] = {
                    "ch": _normalize_channel(info.channel),
                    "bw": _bandwidth_for_band(band, mbps),
                    "txPower": "23dBm" if band == "6G" else "25dBm",
                    "txUti": 0,
                    "rxUti": 0,
                    "interUti": 0,
                    "busyUti": 0,
                    "staNum": band_sta_num,
                }
                if mbps is not None:
                    w_settings["rdMode"] = "11be"
                    w_settings["txR"] = f"{mbps}.0Mbps"
                payload[f"wSettings_{suffix}"] = w_settings
                payload[f"ssidStats_{suffix}"] = [
                    {
                        "id": int(ids_now.get((band, info.ssid), 0)),
                        "ssid": info.ssid,
                        "bssid": to_omada(info.mac),
                        "clntNum": count,
                    }
                ]
            if payload:
                self._cached = payload
                self._cached_ids_snapshot = ids_now
                self._ts = ts
            return payload
        except Exception as exc:
            age = max(0.0, ts - self._ts)
            if self._station_source is None and self._cached and self._stale_ttl_s > 0.0 and age < self._stale_ttl_s:
                log.warning(
                    "netgear wireless inform failed (%s); serving cached payload (age=%.1fs)",
                    exc,
                    age,
                )
                return self._cached
            log.warning("netgear wireless inform failed: %s", exc)
            return {}


class NetgearClientSource:
    """Poll-merged client view: Netgear's GetAttachDevice returns a
    churning subset per call, so clients are aged out after `expire_s`
    instead of trusting any single poll."""

    def __init__(
        self,
        adapter: NetgearAdapter,
        *,
        expire_s: float = 300.0,
        physical_mac: str | None = None,
        bands: tuple[str, ...] = ("2.4G", "5G", "6G"),
        now: Callable[[], float] = time.time,
    ) -> None:
        self._adapter = adapter
        self._physical_mac = unicast_mac(physical_mac)
        if physical_mac is not None and self._physical_mac is None:
            raise ValueError("OMADA_NETGEAR_PHYSICAL_MAC must be a valid unicast hardware MAC")
        self._expire_s = expire_s
        self._bands = bands
        self._now = now
        self._seen: dict[str, tuple[WirelessClientState, float]] = {}

    def __call__(self) -> tuple[WirelessClientState, ...]:
        age = 0.0
        try:
            snapshot = getattr(self._adapter, "read_clients_with_age", None)
            if self._physical_mac is not None and snapshot is not None:
                clients, age = snapshot()
            else:
                clients = self._adapter.read_clients()
        except Exception as exc:
            log.warning("netgear client poll failed: %s", exc)
            clients = []
        if self._physical_mac is not None:
            clients = self._owned_clients(clients)
        fallback_band = self._bands[0] if len(self._bands) == 1 else None
        fallback_ssid = ""
        if fallback_band is not None and any(
            c.connection == "wireless" and not c.band for c in clients
        ):
            try:
                fallback_ssid = self._adapter.read_state()[fallback_band].ssid
            except Exception as exc:
                log.warning("netgear client state poll failed: %s", exc)
        ts = self._now()
        for c in clients:
            try:
                mac = MacAddress(c.mac).value
            except ValueError:
                log.warning("netgear: skipping client with invalid MAC %r", c.mac)
                continue
            if c.connection != "wireless":
                # Omada Controller 6.3 ApClientImage throws IllegalArgumentException
                # and aborts the entire DEVICE_INFORM batch if an EAP reports a client
                # without a radioId (rid). Wired pass-through hosts stay on the upstream
                # switch port instead of entering EAP wireless informs.
                self._seen.pop(mac, None)
                continue
            radio = _CLIENT_BANDS.get(c.band or fallback_band)
            if radio is None:
                continue
            rate_kbps = (
                c.link_rate_mbps * 1000
                if c.link_rate_mbps is not None and c.link_rate_mbps > 0
                else None
            )
            self._seen[mac] = (WirelessClientState(
                mac=mac,
                wireless=True,
                ipv4=c.ip or None,
                hostname=c.name or None,
                ssid=c.ssid or (fallback_ssid if not c.band else "") or None,
                radio=radio,
                rssi=c.signal_dbm,
                rx_rate=rate_kbps,
                tx_rate=rate_kbps,
            ), ts - age)
        self._seen = {m: v for m, v in self._seen.items() if ts - v[1] <= self._expire_s}
        return self.current_stations()

    def current_stations(self) -> tuple[WirelessClientState, ...]:
        """Station snapshot already obtained for this inform, with no second SOAP read."""
        return tuple(state for state, _ in self._seen.values())

    def _owned_clients(self, rows: list[AttachedClient]) -> list[AttachedClient]:
        # A wired/foreign row withdraws the station even if this same response
        # also contains a contradictory local row. Missing identity says nothing.
        owned: dict[str, AttachedClient] = {}
        departed: set[str] = set()
        for row in rows:
            station = unicast_mac(row.mac)
            if station is None:
                continue
            ap = unicast_mac(getattr(row, "reported_ap_mac", None))
            if row.connection == "wired" or (ap is not None and ap != self._physical_mac):
                departed.add(station)
            elif ap == self._physical_mac and row.connection == "wireless":
                owned[station] = row
        for station in departed:
            self._seen.pop(station, None)
            owned.pop(station, None)
        return list(owned.values())
