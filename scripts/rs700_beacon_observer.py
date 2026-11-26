#!/usr/bin/env python3
"""Print selected radios from the local wpa_supplicant BSS cache as JSON.

Repeat --bssid for each configured radio. The invoking account needs access to
the interface's control socket. This command neither scans nor associates.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time


def bssid_arg(value: str) -> str:
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
        raise argparse.ArgumentTypeError("expected a six-octet colon-separated BSSID")
    value = value.lower()
    if int(value[:2], 16) & 1 or value == "00:00:00:00:00:00":
        raise argparse.ArgumentTypeError("expected a nonzero unicast BSSID")
    return value


def bss_load(ies_hex: str) -> int | None:
    """Read the channel-utilization octet of an 802.11 BSS Load information element."""
    try:
        elements = bytes.fromhex(ies_hex)
    except ValueError:
        return None
    index = 0
    utilization = None
    while index < len(elements):
        if index + 2 > len(elements):
            return None
        kind, length = elements[index : index + 2]
        start = index + 2
        index = start + length
        if index > len(elements):
            return None
        if kind == 11:
            if length != 5 or utilization is not None:
                return None
            utilization = elements[start + 2]
    return utilization


def observation(output: str, bssid: str, now: int) -> dict[str, int] | None:
    fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    if fields.get("bssid", "").lower() != bssid:
        return None
    try:
        age = int(fields["age"])
        frequency = int(fields["freq"])
    except (KeyError, ValueError):
        return None
    if not 0 <= age < now or not 2400 <= frequency <= 7125:
        return None

    result = {"observed_at": now - age, "frequency_mhz": frequency}
    for field in ("ie", "beacon_ie"):
        utilization = bss_load(fields.get(field, ""))
        if utilization is not None:
            result["utilization_255"] = utilization
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", required=True, help="local managed Wi-Fi interface")
    parser.add_argument("--bssid", required=True, action="append", type=bssid_arg)
    args = parser.parse_args()
    radios = {}
    for bssid in dict.fromkeys(args.bssid):
        now = int(time.time())
        try:
            response = subprocess.run(
                ["wpa_cli", "-i", args.interface, "bss", bssid],
                check=True, capture_output=True, encoding="utf-8", errors="replace", timeout=3,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Could not read the BSS cache on {args.interface}: {exc}", file=sys.stderr)
            return 1
        item = observation(response.stdout, bssid, now)
        if item is not None:
            radios[bssid] = item
    print(json.dumps({"version": 1, "radios": radios}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
