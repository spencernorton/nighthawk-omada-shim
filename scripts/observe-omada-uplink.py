#!/usr/bin/env python3
"""Emit byte counters only for a verified AP attachment on its dedicated switch port.

Reads a read-only Omada controller account from either:
- OMADA_CREDS pointing to a JSON file containing {"url", "site", "user", "password"}
  (and optional "ca_file"), or
- OMADA_CONTROLLER_URL, OMADA_SITE_NAME, OMADA_VIEWER_USERNAME, and
  OMADA_VIEWER_PASSWORD environment variables (plus optional OMADA_TLS_CA_FILE).

TLS certificate verification is enabled by default. Set OMADA_TLS_VERIFY=false
only when connecting to a private controller with a self-signed certificate.
Requires the optional `tplink-omada-client` package (`pip install '.[uplink]'`).
"""
import argparse
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time


class UnqualifiedObservation(ValueError):
    pass


def mac_address(value):
    compact = value.replace("-", "").replace(":", "")
    if not re.fullmatch(r"[0-9a-fA-F]{12}", compact):
        raise argparse.ArgumentTypeError("invalid MAC address")
    return "-".join(compact[i:i + 2].upper() for i in range(0, 12, 2))


def observation(ap, switch, args, now):
    if not (ap.get("mac") == args.ap_mac and ap.get("ip") == args.ap_ip
            and ap.get("active") is True and ap.get("wireless") is False
            and ap.get("switchMac") == args.switch_mac and ap.get("port") == args.port):
        raise UnqualifiedObservation("AP attachment unverified")
    if switch.get("mac") != args.switch_mac or switch.get("status") != 14:
        raise UnqualifiedObservation("switch is not connected")
    for record in (ap, switch):
        last_seen = record.get("lastSeen")
        if type(last_seen) is not int or not (now - 60) * 1000 <= last_seen <= (now + 2) * 1000:
            raise UnqualifiedObservation("source observation expired")
    port = next((p for p in switch["ports"] if p["port"] == args.port), None)
    if not port or port.get("disable") is not False:
        raise UnqualifiedObservation("port unavailable")
    status = port.get("portStatus") or {}
    if status.get("port") != args.port or status.get("linkStatus") != 1:
        raise UnqualifiedObservation("uplink unavailable")
    for key in ("tx", "rx"):
        if type(status.get(key)) is not int or not 0 <= status[key] < 2**63:
            raise UnqualifiedObservation("invalid byte counter")
    return {"version": 1, "ap_mac": args.ap_mac, "ap_ip": args.ap_ip,
            "switch_mac": args.switch_mac, "port": args.port,
            "observed_at_ms": switch["lastSeen"],
            "switch_tx_bytes": status["tx"], "switch_rx_bytes": status["rx"]}


def load_controller_credentials():
    creds_path = os.environ.get("OMADA_CREDS", "").strip()
    if creds_path:
        data = json.loads(Path(creds_path).read_text(encoding="utf-8"))
        url = str(data.get("url", "")).strip()
        site = str(data.get("site", "")).strip()
        user = str(data.get("user", "")).strip()
        password = str(data.get("password", ""))
        ca_file = str(data.get("ca_file", "")).strip()
    else:
        url = os.environ.get("OMADA_CONTROLLER_URL", "").strip()
        site = os.environ.get("OMADA_SITE_NAME", "Default").strip()
        user = os.environ.get("OMADA_VIEWER_USERNAME", "").strip()
        password = os.environ.get("OMADA_VIEWER_PASSWORD", "")
        ca_file = os.environ.get("OMADA_TLS_CA_FILE", "").strip()
    if not (url and site and user and password):
        raise UnqualifiedObservation("explicit read-only controller credentials required")
    verify_raw = os.environ.get("OMADA_TLS_VERIFY", "true").strip().lower()
    verify_ssl = verify_raw not in {"0", "false", "no", "off"}
    return {
        "url": url,
        "site": site,
        "user": user,
        "password": password,
        "verify_ssl": verify_ssl,
        "ca_file": ca_file,
    }


async def collect(args):
    from tplink_omada_client import OmadaClient

    credentials = load_controller_credentials()
    verify_ssl = credentials["verify_ssl"]
    if verify_ssl and credentials["ca_file"]:
        ssl_context = ssl.create_default_context(cafile=credentials["ca_file"])
        verify_opt = ssl_context
    else:
        verify_opt = verify_ssl
    async with OmadaClient(
        credentials["url"],
        credentials["user"],
        credentials["password"],
        verify_ssl=verify_opt,
    ) as client:
        sites = await client.get_sites()
        site_match = next((s for s in sites if s.name == credentials["site"]), None)
        if site_match is None:
            raise UnqualifiedObservation("configured Omada site not found")
        site = await client.get_site_client(site_match)
        ap = (await site.get_client(args.ap_mac))._data
        switch = (await site.get_switch(args.switch_mac))._data
        return observation(ap, switch, args, time.time())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--switch-mac", type=mac_address, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ap-mac", type=mac_address, required=True)
    parser.add_argument("--ap-ip", type=lambda s: str(ipaddress.IPv4Address(s)), required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(collect(args))
    except UnqualifiedObservation as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # The SDK may include an HTTP response in its exception text.
        print(f"uplink observation unavailable ({type(error).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
