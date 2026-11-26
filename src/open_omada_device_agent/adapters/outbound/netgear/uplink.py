"""Project fresh dedicated switch-port byte counters into the AP's wired uplink."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
import time

from ....util.uptime import parse_ecsp_uptime


MAX_AGE_SECONDS = 75


@dataclass(frozen=True)
class PortSample:
    timestamp: int
    rx: int
    tx: int
    attachment: tuple[str, str, int]


def read_port_sample(path: Path, ap_ip: str, now: float) -> PortSample | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or type(data.get("version")) is not int:
            return None
        if data["version"] != 1 or data.get("ap_ip") != ap_ip:
            return None
        timestamp = data["observed_at_ms"]
        if type(timestamp) is not int or not (now - MAX_AGE_SECONDS) * 1000 <= timestamp <= (now + 2) * 1000:
            return None
        rx, tx = data["switch_tx_bytes"], data["switch_rx_bytes"]
        if any(type(v) is not int or not 0 <= v < 2**63 for v in (rx, tx)):
            return None
        attachment = (data["ap_mac"], data["switch_mac"], data["port"])
        if not all(isinstance(mac, str) and re.fullmatch(r"(?:[0-9A-F]{2}-){5}[0-9A-F]{2}", mac)
                   for mac in attachment[:2]):
            return None
        if type(attachment[2]) is not int or attachment[2] < 1:
            return None
        return PortSample(timestamp, rx, tx, attachment)
    except (KeyError, OSError, UnicodeError, ValueError, RecursionError):
        return None


class ObservedUplink:
    def __init__(self, path: Path, ap_ip: str, *, now=time.time):
        self.path = path
        self.ap_ip = ap_ip
        self.now = now
        self.previous: PortSample | None = None
        self.uptime: int | None = None
        self.cleared = False

    def __call__(self, port: str, uptime_text: str) -> dict | None:
        now = self.now()
        sample = read_port_sample(self.path, self.ap_ip, now)
        if sample is None:
            # Omission alone leaves the last rate on the controller indefinitely.
            if not self.cleared and (self.previous is None or
                    now - self.previous.timestamp / 1000 > MAX_AGE_SECONDS):
                self.previous = None
                self.uptime = None
                self.cleared = True
                return {"port": port}
            return None
        try:
            uptime = parse_ecsp_uptime(uptime_text)
        except ValueError:
            return None
        if uptime <= 0:
            return None
        previous = self.previous
        if previous and sample.timestamp <= previous.timestamp:
            return None
        reset = previous is None and not self.cleared
        if previous is not None and self.uptime is not None:
            elapsed = (sample.timestamp - previous.timestamp) / 1000
            reset = (previous.attachment != sample.attachment
                     or sample.rx < previous.rx or sample.tx < previous.tx
                     or elapsed > MAX_AGE_SECONDS or uptime <= self.uptime
                     or abs(uptime - self.uptime - elapsed) > 30)
        self.previous = sample
        self.uptime = uptime
        self.cleared = reset
        if reset:
            # Clear the controller's old byte baseline. On a restart/decreasing
            # counter Omada otherwise divides a switch-lifetime total by AP uptime.
            return {"port": port}
        return {"port": port, "rx": sample.rx, "tx": sample.tx}
