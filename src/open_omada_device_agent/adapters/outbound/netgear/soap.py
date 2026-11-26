"""Netgear Genie SOAP client and response parsing.

Verified live against an RS700 (SOAPVersion 3.84, firmware V1.0.11.8):
SOAPLogin on DeviceConfig establishes a cookie session; WLANConfiguration
GetInfo/Get5GInfo/Get6GInfo report per-band state; DeviceInfo GetAttachDevice
reports clients as ``idx;ip;name;mac;type;rate;signal;policy`` entries where
signal is an integer percent (wired clients carry a placeholder of 100).
"""
from __future__ import annotations

import logging
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol
from xml.sax.saxutils import escape

from ....util.uptime import parse_ecsp_uptime

log = logging.getLogger(__name__)

SOAP_PATH = "/soap/server_sa/"
SESSION_PLACEHOLDER = "A7D88AE69687E58D9A00"


_LEADING_INT_RE = re.compile(r"^\s*(\d+)")


def parse_wireless_mode_mbps(mode: str) -> int | None:
    """Extract negotiated PHY ceiling in Mbit/s from Netgear NewWirelessMode
    (e.g. ``'688Mbps'``, ``'5765Mbps'``, ``'11529Mbps'``)."""
    if not mode:
        return None
    match = _LEADING_INT_RE.match(mode)
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def parse_netgear_uptime(raw: str) -> int | None:
    """Parse DeviceInfo.GetSysUpTime ``SysUpTime`` (``'3 days 09:01:10'``
    or ``'09:01:10'``) into elapsed seconds."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return parse_ecsp_uptime(text)
    except ValueError:
        pass
    parts = text.split(":")
    if len(parts) == 3 and all(piece.strip().isdigit() for piece in parts):
        hh, mm, ss = (int(piece.strip()) for piece in parts)
        return hh * 3600 + mm * 60 + ss
    if text.isdigit():
        return int(text)
    return None


def signal_percent_to_dbm(percent: int) -> int:
    """Approximate percent->dBm mapping. Documented approximation only:
    the percent value is Netgear's own conversion of true RSSI, so the
    result is suitable for relative strength, not RF engineering."""
    return percent // 2 - 100


def _optional_int(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text.isascii() or not text.isdecimal():
        return None
    return int(text)


def _optional_percent(raw: str | None) -> int | None:
    value = _optional_int(raw)
    return value if value is not None and value <= 100 else None


def _optional_text(raw: str | None) -> str | None:
    return (raw or "").strip() or None


@dataclass(frozen=True)
class AttachedClient:
    ip: str
    name: str
    mac: str
    connection: str  # "wireless" | "wired" | "unknown"
    link_rate_mbps: int | None
    signal_percent: int | None
    policy: str = ""
    band: str = ""  # "2.4G" | "5G" | "6G" when GetAttachDevice2 knows it
    ssid: str = ""
    device_type_name: str = ""
    device_brand: str = ""
    device_model: str = ""
    reported_ap_mac: str | None = None

    @property
    def signal_dbm(self) -> int | None:
        if self.connection != "wireless" or self.signal_percent is None:
            return None
        return signal_percent_to_dbm(self.signal_percent)


def parse_attach_devices(raw_value: str) -> list[AttachedClient]:
    """Parse the NewAttachDevice payload: ``count@entry@entry...``."""
    if not raw_value or "@" not in raw_value:
        return []
    _count, _, rest = raw_value.partition("@")
    clients: list[AttachedClient] = []
    for entry in rest.split("@"):
        parts = entry.split(";")
        if len(parts) < 8:
            continue
        _idx, ip, name, mac, conn = parts[0], parts[1], parts[2], parts[3], parts[4]
        rate = _optional_int(parts[5])
        signal = _optional_percent(parts[6])
        if conn == "wired":
            signal = None  # placeholder 100 carries no RF meaning
        clients.append(AttachedClient(ip=ip, name=name, mac=mac.upper(),
                                      connection=conn, link_rate_mbps=rate,
                                      signal_percent=signal, policy=parts[7]))
    return clients


@dataclass(frozen=True)
class BandState:
    band: str  # "2.4G" | "5G" | "6G"
    ssid: str
    enabled: bool
    broadcast: bool
    channel: str
    wireless_mode: str
    security: str
    mac: str
    status: str | None = None
    region: str | None = None
    wpa_encryption_modes: str | None = None


_BAND_PREFIXES = (("2.4ghz", "2.4G"), ("5ghz", "5G"), ("6ghz", "6G"))


def _band_for_connection(connection_type: str) -> str:
    """Map Netgear ConnectionType (including '- Guest' / IoT suffixes) to radio band."""
    normalized = connection_type.strip().casefold()
    for prefix, band in _BAND_PREFIXES:
        if normalized.startswith(prefix):
            return band
    return ""


def _connection_for_type(connection_type: str) -> tuple[str, str]:
    band = _band_for_connection(connection_type)
    if band:
        return "wireless", band
    if connection_type.strip().casefold() in {"ethernet", "wired"}:
        return "wired", ""
    return "unknown", ""


def parse_attach_devices_detailed(xml_text: str) -> list[AttachedClient]:
    """Parse GetAttachDevice2: repeated <Device> records with band/SSID."""
    clients: list[AttachedClient] = []
    for device in ET.fromstring(xml_text).iter():
        if device.tag.split("}")[-1] != "Device":
            continue
        fields = {el.tag.split("}")[-1]: (el.text or "").strip()
                  for el in device if len(el) == 0}
        mac = fields.get("MAC", "").upper()
        if not mac:
            continue
        connection, band = _connection_for_type(fields.get("ConnectionType", ""))
        clients.append(AttachedClient(
            ip=fields.get("IP", ""), name=fields.get("Name", ""), mac=mac,
            connection=connection,
            link_rate_mbps=_optional_int(fields.get("Linkspeed")),
            signal_percent=_optional_percent(fields.get("SignalStrength")) if band else None,
            policy=fields.get("AllowOrBlock", ""), band=band,
            ssid=fields.get("SSID", ""),
            device_type_name=fields.get("DeviceTypeNameV2", ""),
            device_brand=fields.get("DeviceBrand", ""),
            device_model=fields.get("DeviceModel", ""),
            reported_ap_mac=(_optional_text(fields.get("ConnAPMAC")) or "").upper() or None,
        ))
    return clients


def parse_band_state(band: str, fields: dict[str, str]) -> BandState:
    return BandState(
        band=band,
        ssid=fields.get("NewSSID", ""),
        enabled=fields.get("NewEnable", "0") == "1",
        broadcast=fields.get("NewSSIDBroadcast", "0") == "1",
        channel=fields.get("NewChannel", ""),
        wireless_mode=fields.get("NewWirelessMode", ""),
        security=fields.get("NewBasicEncryptionModes", ""),
        mac=fields.get("NewWLANMACAddress", "").upper(),
        status=_optional_text(fields.get("NewStatus")),
        region=_optional_text(fields.get("NewRegion")),
        wpa_encryption_modes=_optional_text(fields.get("NewWPAEncryptionModes")),
    )


@dataclass(frozen=True)
class SystemInfo:
    load_average_x100: int | None
    free_memory_percent: int | None

    @property
    def used_memory_percent(self) -> int | None:
        if self.free_memory_percent is None:
            return None
        return 100 - self.free_memory_percent


def parse_system_info(fields: dict[str, str]) -> SystemInfo:
    """NewCPUUtilization is load-average×100; memory is free/buffer/cache percent."""
    return SystemInfo(
        load_average_x100=_optional_int(fields.get("NewCPUUtilization")),
        free_memory_percent=_optional_percent(fields.get("NewMemoryUtilization")),
    )


def response_fields(xml_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    root = ET.fromstring(xml_text)
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if el.text and el.text.strip() and len(el) == 0:
            out[tag] = el.text.strip()
    return out


class Transport(Protocol):
    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[str, str]:
        """Return (response_text, set_cookie)."""
        ...


class UrllibTransport:
    def __init__(self, timeout: int = 35) -> None:
        self._timeout = timeout
        self._ctx = ssl._create_unverified_context()

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[str, str]:
        req = urllib.request.Request(url, data=body, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, context=self._ctx, timeout=self._timeout) as r:
            return r.read().decode(errors="ignore"), r.headers.get("Set-Cookie", "")


class SoapError(RuntimeError):
    pass


class NetgearSoapClient:
    """Stateful Genie SOAP client (cookie session via SOAPLogin)."""

    def __init__(self, host: str, username: str, password: str,
                 transport: Transport | None = None) -> None:
        self._url = f"https://{host}:443{SOAP_PATH}"
        self._username = username
        self._password = password
        self._transport = transport or UrllibTransport()
        self._cookie = ""

    def _post(self, service: str, method: str, params: dict[str, str] | None = None) -> str:
        inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in (params or {}).items())
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<SOAP-ENV:Body><m:{method} xmlns:m="urn:NETGEAR-ROUTER:service:{service}:1">'
            f"{inner}</m:{method}></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        ).encode()
        headers = {"Content-Type": "text/xml; charset=utf-8",
                   "SOAPAction": f"urn:NETGEAR-ROUTER:service:{service}:1#{method}"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        text, cookie = self._transport.post(self._url, body, headers)
        if method == "SOAPLogin" and cookie:
            self._cookie = cookie
        return text

    def call(self, service: str, method: str, params: dict[str, str] | None = None) -> dict[str, str]:
        fields = response_fields(self._post(service, method, params))
        code = fields.get("ResponseCode", "")
        if code == "401" and method != "SOAPLogin":
            # Genie sessions expire under long-running informs; re-login
            # once and retry instead of degrading every later poll.
            log.info("netgear SOAP session expired (401) on %s.%s; re-logging in",
                     service, method)
            self.login()
            fields = response_fields(self._post(service, method, params))
            code = fields.get("ResponseCode", "")
        if code not in ("000", ""):
            raise SoapError(f"{service}.{method} failed: ResponseCode={code}")
        return fields

    def login(self) -> None:
        self.call("DeviceConfig", "SOAPLogin",
                  {"Username": self._username, "Password": self._password})
        if not self._cookie:
            raise SoapError("SOAPLogin returned no session cookie")

    # -- reads ---------------------------------------------------------
    def device_info(self) -> dict[str, str]:
        return self.call("DeviceInfo", "GetInfo")

    def system_info(self) -> SystemInfo:
        return parse_system_info(self.call("DeviceInfo", "GetSystemInfo"))

    def sys_uptime_seconds(self) -> int | None:
        fields = self.call("DeviceInfo", "GetSysUpTime")
        return parse_netgear_uptime(fields.get("SysUpTime", ""))

    def band_state(self, band: str) -> BandState:
        method = {"2.4G": "GetInfo", "5G": "Get5GInfo", "6G": "Get6GInfo"}[band]
        return parse_band_state(band, self.call("WLANConfiguration", method))

    def attached_clients(self) -> list[AttachedClient]:
        fields = self.call("DeviceInfo", "GetAttachDevice")
        return parse_attach_devices(fields.get("NewAttachDevice", ""))

    def attached_clients_detailed(self) -> list[AttachedClient]:
        """GetAttachDevice2 with per-client band/SSID; callers fall back
        to attached_clients() on any failure (older firmware)."""
        text = self._post("DeviceInfo", "GetAttachDevice2")
        code = response_fields(text).get("ResponseCode", "")
        if code == "401":
            log.info("netgear SOAP session expired (401) on GetAttachDevice2; re-logging in")
            self.login()
            text = self._post("DeviceInfo", "GetAttachDevice2")
            code = response_fields(text).get("ResponseCode", "")
        if code not in ("000", ""):
            raise SoapError(f"DeviceInfo.GetAttachDevice2 failed: ResponseCode={code}")
        return parse_attach_devices_detailed(text)

    def current_psk(self, band: str) -> str:
        method = {"2.4G": "GetWPASecurityKeys", "5G": "Get5GWPASecurityKeys",
                  "6G": "Get6GWPASecurityKeys"}[band]
        return self.call("WLANConfiguration", method).get("NewWPAPassphrase", "")

    # -- writes (proven live with same-value sets; see plan Step 1) -----
    def set_channel(self, band: str, channel: str) -> None:
        method = {"2.4G": "SetChannel", "5G": "Set5GChannel", "6G": "Set6GChannel"}[band]
        self.call("WLANConfiguration", method, {"NewChannel": channel})

    def set_guest_enabled(self, band: str, enabled: bool) -> None:
        method = {"2.4G": "SetGuestAccessEnabled", "5G": "Set5GGuestAccessEnabled",
                  "6G": "Set6GGuestAccessEnabled"}[band]
        self.call("WLANConfiguration", method,
                  {"NewGuestAccessEnabled": "1" if enabled else "0"})

    def set_psk(self, band: str, ssid: str, passphrase: str) -> None:
        method = {"2.4G": "SetWLANWPAPSKByPassphrase",
                  "5G": "Set5GWLANWPAPSKByPassphrase",
                  "6G": "Set6GWLANWPAPSKByPassphrase"}[band]
        self.call("WLANConfiguration", method,
                  {"NewSSID": ssid, "NewWPAEncryptionModes": "WPA2/WPA3-Personal",
                   "NewWPAPassphrase": passphrase})
