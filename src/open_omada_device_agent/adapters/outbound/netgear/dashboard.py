"""Read only the three status views of a stock RS700S through its normal authenticated UI."""

import base64
import hashlib
import hmac
import http.client
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from dataclasses import dataclass
import ipaddress
import logging
import threading
import time
from collections.abc import Callable
import re
import ssl
from urllib.parse import urljoin, urlsplit
from urllib.request import Request


OVERVIEW = "/ADVANCED_home2_tri_band.htm"
STATISTICS = "/RST_statistics.htm"
PATHS = {"/", "/start.htm", OVERVIEW, STATISTICS}
BANDS = {"wireless": "2G", "wireless_an": "5G", "wireless_6g": "6G"}
PORTS = ("WAN", "LAN1", "LAN2", "LAN3", "LAN4", "LAN 10G")
MAX_BODY = 1024 * 1024


class PanelError(ValueError):
    """An expected, non-sensitive protocol or data error."""


class RejectedCredential(PanelError):
    """Stop until the operator corrects the credential and restarts the process."""


class ReadSession:
    def __init__(self, host: str, certificate_sha256: str, username: str, password: str):
        try:
            self.host = str(ipaddress.ip_address(host))
        except ValueError:
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host):
                raise ValueError("Invalid dashboard hostname") from None
            self.host = host.lower()
        if not username or ":" in username:
            raise ValueError("Invalid dashboard account")
        if not re.fullmatch("[a-fA-F0-9]{64}", certificate_sha256) or not password:
            raise ValueError("A trusted certificate pin and credential are required")
        self.pin = bytes.fromhex(certificate_sha256)
        self.origin = "https://" + ("[" + self.host + "]" if ":" in self.host else self.host)
        self.auth = "Basic " + base64.b64encode((username + ":" + password).encode()).decode(
            "ascii"
        )
        self.cookies = CookieJar()
        self.challenged = False
        self.authenticated = False
        self._deadline = 0.0
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.tls.check_hostname = False
        self.tls.verify_mode = ssl.CERT_NONE  # Match the enrolled DER pin before ANY HTTP request.
        self.tls.minimum_version = ssl.TLSVersion.TLSv1_2

    def _exchange(self, path, referrer):
        if path not in PATHS or (referrer is not None and referrer not in PATHS):
            raise PanelError("Unexpected stock UI route")
        req = Request(
            self.origin + path, headers={"Accept": "text/html", "User-Agent": "RS700-status/1"}
        )
        if self.challenged:
            req.add_header("Authorization", self.auth)
        if referrer:
            req.add_header("Referer", self.origin + referrer)
        self.cookies.add_cookie_header(req)
        def timeout():
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Dashboard read deadline")
            return min(6.0, remaining)

        conn = http.client.HTTPSConnection(self.host, timeout=timeout(), context=self.tls)
        try:
            conn.connect()
            if not hmac.compare_digest(
                hashlib.sha256(conn.sock.getpeercert(binary_form=True)).digest(), self.pin
            ):
                raise PanelError("Router certificate pin mismatch")
            transport = conn.sock
            transport.settimeout(timeout())
            conn.request("GET", path, headers=dict(req.header_items()))
            res = conn.getresponse()
            self.cookies.extract_cookies(res, req)
            body = bytearray()
            with res:
                while len(body) <= MAX_BODY:
                    if res.isclosed():
                        return res.status, res.headers, bytes(body)
                    transport.settimeout(timeout())
                    chunk = res.read1(min(65536, MAX_BODY + 1 - len(body)))
                    if not chunk:
                        return res.status, res.headers, bytes(body)
                    body.extend(chunk)
                raise PanelError("Status response exceeds bound")
        finally:
            conn.close()

    def get(self, path, referrer=None):
        status, headers, body = self._exchange(path, referrer)
        if status == 401 and not self.challenged:
            if not any(
                re.match(r"^\s*Basic\s+realm\s*=", v, re.I)
                for v in headers.get_all("WWW-Authenticate", [])
            ):
                raise PanelError("Expected normal Basic realm challenge")
            self.challenged = True
            status, headers, body = self._exchange(path, referrer)
            if status in (401, 403, 429):
                raise RejectedCredential("Dashboard rejected the enrolled account")
        if status in (301, 302, 303, 307, 308) and path == "/":
            target = urlsplit(urljoin(self.origin + "/", headers.get("Location", "")))
            if (
                target.scheme == "https"
                and target.netloc == urlsplit(self.origin).netloc
                and target.path == "/start.htm"
                and not target.query
            ):
                return self.get("/start.htm", "/")
        if status != 200:
            raise PanelError(f"HTTP {status} for {path}")
        return path, body.decode("utf-8", errors="replace")

    def read(self):
        self._deadline = time.monotonic() + 20
        if not self.authenticated:
            path, home = self.get("/")
            if path == "/" and re.search(
                r'location\.replace\(\s*["\x27]start\.htm["\x27]\s*\)', home, re.I
            ):
                path, home = self.get("/start.htm", "/")
            if self.challenged and path != "/start.htm":
                raise RejectedCredential("Dashboard login did not reach the authenticated homepage")
            if path != "/start.htm" or not self.challenged:
                raise PanelError("Normal authenticated homepage was not reached")
            self.authenticated = True
        _, overview = self.get(OVERVIEW, "/start.htm")
        _, statistics = self.get(STATISTICS, OVERVIEW)
        return overview, statistics


class Tables(HTMLParser):
    """Read direct row cells from named tables; scripts and unrelated content stay out."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.result = {}
        self.row = None
        self.cell = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "table":
            name = dict(attrs).get("id", "")
            key = name if name in (*BANDS, "statistic_table") else None
            if key and key in self.result:
                raise PanelError("Duplicate stock status table")
            if key:
                self.result[key] = []
            self.stack.append((key, self.row, self.cell))
            self.row = self.cell = None
        elif self.stack and self.stack[-1][0]:
            if tag == "tr":
                self.row = []
            elif tag in ("th", "td") and self.row is not None:
                self.cell = []
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")

    def handle_data(self, text):
        if self.cell is not None and not self.skip:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "table" and self.stack:
            _, self.row, self.cell = self.stack.pop()
        elif self.stack and self.stack[-1][0]:
            if tag in ("th", "td") and self.cell is not None and self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.result[self.stack[-1][0]].append(self.row)
                self.row = self.cell = None


def channel(value, band):
    """Use a numeric channel, an Auto singleton or exactly one explicitly marked primary."""
    match = re.fullmatch(r"(?:Auto\s*\(\s*(.*?)\s*\)|(\d{1,3}))", value, re.I)
    if not match:
        return None
    items = [s.strip() for s in (match[1] or match[2] or "").split("+")]
    parsed = [re.fullmatch(r"(\d{1,3})\s*(\(P\))?", s, re.I) for s in items]
    if not parsed or not all(parsed):
        return None
    channels = [int(m[1]) for m in parsed]
    if len(channels) != len(set(channels)):
        return None
    low, high = {"2G": (1, 14), "5G": (32, 177), "6G": (1, 233)}[band]
    if any(not low <= n <= high for n in channels):
        return None
    primary = [int(m[1]) for m in parsed if m[2]]
    if len(primary) == 1:
        return primary[0]
    return channels[0] if len(channels) == 1 else None


@dataclass(frozen=True)
class PhysicalLink:
    up: bool
    mbps: int
    full_duplex: bool | None


@dataclass(frozen=True)
class DashboardStatus:
    channels: dict[str, int]
    uplink: PhysicalLink | None


def physical_link(value: str) -> PhysicalLink | None:
    if value == "Link Down":
        return PhysicalLink(False, 0, None)
    speed, sep, duplex = value.upper().partition("/")
    units = {
        "10M": 10,
        "100M": 100,
        "1000M": 1000,
        "1G": 1000,
        "2500M": 2500,
        "2.5G": 2500,
        "5000M": 5000,
        "5G": 5000,
        "10000M": 10000,
        "10G": 10000,
    }
    if not sep or speed not in units or duplex not in ("HALF", "FULL"):
        return None
    return PhysicalLink(True, units[speed], duplex == "FULL")


def parse_dashboard(overview: str, statistics: str, jack: str) -> DashboardStatus:
    radios, stats = Tables(), Tables()
    radios.feed(overview)
    radios.close()
    stats.feed(statistics)
    stats.close()
    channels = {}
    for key, band in BANDS.items():
        values = [
            row[1]
            for row in radios.result.get(key, [])
            if len(row) == 2 and row[0].casefold() == "channel"
        ]
        if len(values) == 1 and (primary := channel(values[0], band)) is not None:
            channels[band] = primary
    link = None
    headers = ["Port", "Status", "TxPkts", "RxPkts", "Collisions", "Tx B/s", "Rx B/s", "Up Time"]
    rows = stats.result.get("statistic_table", [])
    if rows.count(headers) == 1:
        values = [
            row[1]
            for row in rows[rows.index(headers) + 1 :]
            if len(row) == len(headers) and row[0] == jack
        ]
        if len(values) == 1:
            link = physical_link(values[0])
    if not channels and link is None:
        raise PanelError("No recognized stock dashboard status fields")
    # The statistics page's Tx B/s and Rx B/s are since-startup averages.
    # Current throughput comes from separate switch counter observations.
    return DashboardStatus(channels, link)


class StockDashboard:
    """Single background reader for channels and link; ECSP informs never wait for HTTP."""

    REFRESH = 120
    MAX_AGE = 300
    BACKOFF = 600

    def __init__(
        self,
        session_factory: Callable[[], ReadSession],
        jack: str,
        *,
        now: Callable[[], float] = time.monotonic,
    ):
        if jack not in PORTS:
            raise ValueError("Unsupported NETGEAR dashboard uplink port")
        self._session_factory = session_factory
        self._jack = jack
        self._now = now
        self._lock = threading.Lock()
        self._session = None
        self._worker: threading.Thread | None = None
        self._next_read = 0.0
        self._seen = 0.0
        self._value: DashboardStatus | None = None

    def latest(self) -> DashboardStatus | None:
        with self._lock:
            now = self._now()
            if now >= self._next_read and self._worker is None:
                self._worker = threading.Thread(
                    target=self._refresh, name="rs700-dashboard", daemon=True
                )
                self._worker.start()
            return self._value if now - self._seen < self.MAX_AGE else None

    def _refresh(self):
        delay = self.BACKOFF
        value = None
        started = self._now()
        try:
            if self._session is None:
                self._session = self._session_factory()
            overview, stats = self._session.read()
            value = parse_dashboard(overview, stats, self._jack)
            delay = self.REFRESH
        except RejectedCredential:
            self._session = None
            delay = float("inf")
            logging.getLogger(__name__).warning(
                "Stock dashboard authentication rejected; reader suspended"
            )
        except (OSError, ValueError, http.client.HTTPException):
            self._session = None
            logging.getLogger(__name__).warning(
                "Stock dashboard unavailable; waiting before the next read"
            )
        finally:
            with self._lock:
                if value is not None:
                    self._value = value
                    self._seen = started
                self._next_read = self._now() + delay
                self._worker = None
