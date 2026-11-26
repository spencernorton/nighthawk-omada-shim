"""Overlay fresh, BSSID-matched observations on the RS700 wireless inform."""
import json
from pathlib import Path
import time
from typing import Callable


# NetworkManager may retain a BSS for several minutes between background scans.
# Limit the age of the radio observation itself, independently of file delivery.
MAX_AGE_SECONDS = 300
MAX_DOCUMENT_BYTES = 16384
CHANNEL_BOUNDS = {"2G": (1, 14), "5G": (32, 177), "6G": (1, 233)}


def primary_channel(suffix: str, frequency: object) -> int | None:
    """Translate a primary-channel center frequency in the expected radio band."""
    if not isinstance(frequency, int) or isinstance(frequency, bool):
        return None
    if suffix == "2G" and frequency == 2484:
        return 14
    if suffix == "6G" and frequency == 5935:
        return 2
    ranges = {"2G": (2412, 2472, 2407), "5G": (5160, 5885, 5000),
              "6G": (5955, 7115, 5950)}
    low, high, offset = ranges[suffix]
    if low <= frequency <= high and (frequency - offset) % 5 == 0:
        return (frequency - offset) // 5
    return None


def read_radios(path: Path) -> dict | None:
    try:
        with path.open("rb") as source:
            data = source.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            return None
        document = json.loads(data)
    except (OSError, UnicodeError, ValueError, RecursionError):
        return None
    if not isinstance(document, dict) or type(document.get("version")) is not int:
        return None
    radios = document.get("radios")
    return radios if document["version"] == 1 and isinstance(radios, dict) else None


class ObservedRadioInform:
    def __init__(
        self, wireless: Callable[[], dict[str, object]], path: Path | None = None, *additional: Path,
        now: Callable[[], float] = time.time,
        panel_channels: Callable[[], dict[str, int]] | None = None,
    ) -> None:
        self.wireless = wireless
        self.paths = (path, *additional) if path is not None else additional
        self.now = now
        self.panel_channels = panel_channels
        self._last_router_channels: dict[str, int] = {}
        self._router_changed_at: dict[str, float] = {}
        self.last_observed: dict[str, list[dict]] = {}

    def __call__(self) -> dict[str, object]:
        payload = self.wireless()
        now = self.now()
        if self.panel_channels:
            # Fixed SOAP configuration may have changed since the cached dashboard read.
            # Use the dashboard to resolve Auto. Both sources constrain receiver airtime.
            payload = dict(payload)
            dashboard = self.panel_channels()
            for band, (low, high) in CHANNEL_BOUNDS.items():
                key = f"wSettings_{band}"
                settings = payload.get(key)
                configured = settings.get("ch") if isinstance(settings, dict) else None
                primary = dashboard.get(band)
                if (isinstance(configured, str) and len(configured) <= 3
                        and configured.isascii() and configured.isdecimal()):
                    numeric = int(configured)
                    if low <= numeric <= high:
                        primary = numeric
                if primary is None:
                    continue
                previous = self._last_router_channels.get(band)
                if previous is not None and previous != primary:
                    # Returning to the same channel later starts a new observation
                    # window, even if no receiver file existed during the change.
                    self._router_changed_at[band] = now
                self._last_router_channels[band] = primary
                if isinstance(settings, dict):
                    payload[key] = {**settings, "ch": str(primary)}
        if not payload:
            return payload
        sources = [radios for path in self.paths if (radios := read_radios(path)) is not None]
        if not sources:
            return payload
        result = dict(payload)
        active = [f"wSettings_{band}" for band in ("2G", "5G", "6G")
                  if f"wSettings_{band}" in payload]
        measured = set()
        retained = {}
        for suffix in ("2G", "5G", "6G"):
            settings_key = f"wSettings_{suffix}"
            settings = payload.get(settings_key)
            ssids = payload.get(f"ssidStats_{suffix}")
            if not isinstance(settings, dict) or not isinstance(ssids, list) or not ssids:
                continue
            # NetgearWirelessInform emits one main-SSID row per band, with its
            # router-reported BSSID. Two RS700s can broadcast exactly the same SSID.
            bssid = ssids[0].get("bssid") if isinstance(ssids[0], dict) else None
            if not isinstance(bssid, str):
                continue
            address = bssid.lower().replace("-", ":")
            # One scan may temporarily evict another in-band BSS. Reuse the
            # previous sample only with its original timestamp and exact BSSID.
            candidates = []
            entries = [source.get(address) for source in sources]
            for entry in [*entries, *self.last_observed.get(address, [])]:
                if not isinstance(entry, dict):
                    continue
                stamp = entry.get("observed_at")
                if type(stamp) not in (int, float) or not now - MAX_AGE_SECONDS <= stamp <= now:
                    continue
                if stamp <= self._router_changed_at.get(suffix, float("-inf")):
                    continue
                channel = primary_channel(suffix, entry.get("frequency_mhz"))
                if channel is not None:
                    candidates.append((stamp, channel, entry))
            if not candidates:
                continue
            stamp, channel, observation = max(candidates, key=lambda row: row[0])
            # Keep a channel change as a boundary for older occupancy samples.
            different = (row for row in candidates if row[1] != channel)
            prior_channel = max(different, key=lambda row: row[0], default=None)
            retained[address] = [observation]
            if prior_channel:
                retained[address].append(prior_channel[2])
                if stamp == prior_channel[0]:
                    continue
            if settings.get("ch") not in ("0", "", str(channel)):
                continue
            observed = {**settings, "ch": str(channel)}
            channel_since = prior_channel[0] if prior_channel else float("-inf")
            loads = (row for row in candidates if row[1] == channel and row[0] > channel_since
                     and type(row[2].get("utilization_255")) is int
                     and 0 <= row[2]["utilization_255"] <= 255)
            load = max(loads, key=lambda row: row[0], default=None)
            if load is not None:
                retained[address].append(load[2])
                observed["busyUti"] = round(100 * load[2]["utilization_255"] / 255)
                measured.add(settings_key)
            result[settings_key] = observed
        self.last_observed = retained
        # Omada selects split-channel mode for the whole AP when any radio reports
        # the split. Use its aggregate-only form when all reported radios have a
        # fresh total. Never assign the total to interference, TX, or RX.
        if measured and measured == set(active):
            for key in active:
                for component in ("txUti", "rxUti", "interUti"):
                    result[key].pop(component, None)
        return result
