# Operations: Netgear Nighthawk RS700/RS700S as an Omada EAP

This guide covers running one or more stock-firmware NETGEAR Nighthawk
RS700/RS700S access points beside an Omada Network Application controller
(`6.3+`) using `OMADA_SOUTHBOUND=netgear`.

## Identities in a multi-AP deployment

Each physical Nighthawk AP needs its own shim instance with an isolated state
directory and a unique locally administered virtual MAC address (`02:xx:...`):

| Role | Example Router IP | Example Adopted Virtual MAC | Example Physical LAN MAC |
| --- | --- | --- | --- |
| AP 1 | `192.0.2.10` | `02-00-00-00-00-01` | `02-00-00-00-A0-01` |
| AP 2 | `192.0.2.11` | `02-00-00-00-00-02` | `02-00-00-00-A0-02` |

- The **adopted MAC** (`OMADA_DEVICE_MAC`) identifies the virtual EAP in
  Omada's **Devices** view and isolates its default heartbeat file.
- The **physical LAN MAC** (`OMADA_NETGEAR_PHYSICAL_MAC`) identifies the
  physical router on its upstream Omada switch port and scopes wireless station
  ownership via Genie SOAP `ConnAPMAC` so stations are not double-counted across
  multiple APs.
- Each radio (2.4 GHz, 5 GHz, 6 GHz) also reports its own hardware BSSID.

## Container deployment

See [`docker-compose.example.yml`](../docker-compose.example.yml) for a minimal
starting configuration:

- Run in `network_mode: host` (or on the controller's management L2 subnet) so
  ECSP UDP discovery and TLS management reach the controller.
- Mount a dedicated writable `/state` directory per AP instance so the
  controller-provisioned adoption metadata survives restarts. Removing `/state`
  forces a fresh adoption.
- Supply `OMADA_NETGEAR_PASSWORD` and `OMADA_DEVICE_PASSWORD` via environment
  secrets only; neither password is written to `/state`.
- If you enable optional beacon or uplink observers, mount their parent
  directory read-only (for example `/observations:ro`) so atomic file renames
  are visible inside the running container.

## Verifying health

1. Run `python -m open_omada_device_agent --healthcheck` inside the container
   (or rely on the image `HEALTHCHECK`). It verifies that the heartbeat file for
   the container's configured `OMADA_DEVICE_MAC` exists, is fresh, and matches
   that exact MAC.
2. In Omada **Devices**, confirm each adopted AP shows as **Connected** with the
   expected IP, uplink link speed, three radio channels, and local Wi-Fi clients.
3. Compare a fresh router attachment list against Omada **Clients**: wireless
   stations should appear under their serving AP while wired downstream hosts
   remain attached to the upstream Omada switch port.

## Firmware posture

The verified RS700/RS700S posture is **NETGEAR stock firmware only**. There is
currently no supported OpenWrt, DD-WRT, FreshTomato, or Merlin target for the
RS700S. Stock AP mode disables the router's VLAN/IPTV menu and does not expose
per-SSID tagged-LAN VLAN mappings; accordingly, this shim rejects explicit
per-SSID VLAN assignments rather than acknowledging unapplied changes.

## Rollback (removing the integration)

1. In Omada **Devices**, select the virtual AP and choose **Forget**.
2. Stop and remove the shim container (and optionally delete its `/state`
   directory once retired).

The Nighthawk router retains its own configuration throughout; nothing on the
router depends on the shim to keep serving Wi-Fi.

## Deployment lessons

- **Never bind UDP `29810` on a host that also runs the Omada controller.** The
  controller needs UDP `29810` for its own discovery listener and will fail to
  start if another process binds it. By default (`OMADA_LOCAL_DISCOVERY_PORT=0`)
  the shim discovers from an ephemeral UDP source port and uses direct TCP
  managed reconnect once adopted.
- **Match target architecture** (`linux/amd64` or `linux/arm64`); published
  GHCR release tags provide multi-arch manifests.
- **Persist `/state`.** During first adoption, the controller provisions the
  site Device Account routing metadata into the state file; losing `/state`
  causes the agent to return to factory discovery.

## Known limits (by design — never fake-applied)

- **Single main SSID per radio;** no per-SSID VLAN (including explicit VLAN 1),
  dynamic VLAN, VLAN pools, DHCP Option 82, captive portal, RADIUS/PPSK,
  per-client block/rate-limit, LED control, or Omada firmware upgrades.
- **Numeric channels only:** Genie SOAP `SetChannel` accepts numeric channels.
  Requesting `Auto` when the router is already in `Auto` is an idempotent no-op;
  requesting a fixed-to-Auto transition is rejected as unsupported. Supported
  operations in the same batch may still apply, while the overall `SET` returns
  an error with accumulated reasons.
- **Atomic security validation:** If any per-band WLAN security or VLAN intent
  is unsupported, shared SSID and passphrase writes are skipped on every band.
- **PSK rotation / SSID rename:** Stock RS700S SOAP setters return `402`; change
  the Wi-Fi passphrase or SSID in the Netgear web interface.
- **Signal and station link rates:** RSSI is derived from Netgear's reported
  signal percentage (no SNR is available). Stock firmware returns a single
  negotiated `Linkspeed` per station (copied to both Omada RX/TX link-rate
  fields) and reports `0.00` for per-station `Upload`/`Download` byte counters;
  unknown byte counters emit Omada's required `0` wire placeholder.
- **Wired/wireless separation on Omada 6.3+:** Ceiling EAP informs must emit
  only attributable wireless clients with a valid `rid` (`0`, `1`, `3`). Wired
  pass-through hosts, unknown connection types, and invalid MACs are excluded so
  Omada `ApClientImage` does not abort the inform batch.
- **Bounded SOAP caching:** `GetAttachDevice2` can take 12–18 s synchronously on
  stock RS700S firmware. `OMADA_NETGEAR_CLIENT_TTL` (default `30.0` s) shares
  polls across client and wireless informs, and `OMADA_NETGEAR_STALE_TTL`
  (default `180.0` s) bounds end-to-end cache age across all layers.
- **Router memory and CPU metrics:** `DeviceInfo.GetSystemInfo` supplies real
  used memory as `100 - NewMemoryUtilization` (retaining measured zero and
  omitting `memUti` on error or expiry without falling back to container host
  metrics). `NewCPUUtilization` reflects load average × 100 rather than CPU
  utilization, so `cpuUti` is omitted. Note that Omada retains the last
  displayed `memUti` when later informs omit the field.

## Stock dashboard link speed and primary channels

Setting `OMADA_NETGEAR_DASHBOARD_CERT_SHA256` to the 64-hex DER SHA-256
fingerprint of your router's HTTPS certificate enables an authenticated
background reader for the stock **Advanced** and **Show Statistics** pages:

- Polls at most once every two minutes; observations expire after five minutes;
  failures back off for ten minutes.
- Reads the primary operating channel `(P)` on auto-selected radios and the
  negotiated Ethernet speed/duplex for the physical port named by
  `OMADA_NETGEAR_DASHBOARD_UPLINK` (`WAN`, `LAN1`–`LAN4`, or `LAN 10G`).
- Until a fresh dashboard observation arrives, the shim falls back to
  `OMADA_LAN_RATE` and `OMADA_LAN_DUPLEX`.
- Dashboard Wi-Fi `Tx B/s` and `Rx B/s` columns are since-startup averages and
  are deliberately excluded from live traffic rates.

## Passive operating channels and BSS Load airtime

When the router runs in `Auto` channel mode and you want aggregate channel
utilization (`busyUti`), a nearby Linux host with a managed Wi-Fi interface can
publish cached 802.11 BSS Load observations from `wpa_supplicant` without
triggering active scans:

```bash
python3 scripts/rs700_beacon_observer.py --interface wlan0 \
  --bssid 02:00:00:00:a1:02 \
  --bssid 02:00:00:00:a1:03 \
  --bssid 02:00:00:00:a1:04 > /path/to/observations/receiver-1.json.tmp
mv /path/to/observations/receiver-1.json.tmp /path/to/observations/receiver-1.json
```

Configure `OMADA_NETGEAR_BEACON_FILE` (and optionally a second independent
receiver via `OMADA_NETGEAR_SECONDARY_BEACON_FILE`). On each inform, the shim
requires a matching router BSSID, matching frequency band, matching operating
channel, and an observation age ≤ 300 seconds. Complete fresh coverage across
all active radios selects Omada's aggregate-only `busyUti` form; partial
coverage retains Omada's split-mode compatibility placeholders. Individual
TX/RX/interference breakdowns are not provided by 802.11 BSS Load beacons.

## Dedicated switch-port uplink traffic rates

When each Nighthawk AP connects directly to a dedicated Omada-managed switch
port, `scripts/observe-omada-uplink.py` can read cumulative switch-port byte
counters via a read-only Omada account and emit a version-1 JSON snapshot for
`OMADA_NETGEAR_UPLINK_FILE`:

```bash
OMADA_CONTROLLER_URL=https://omada-controller.example.net \
OMADA_SITE_NAME=Default \
OMADA_VIEWER_USERNAME=omada-viewer \
OMADA_VIEWER_PASSWORD=change-me \
python3 scripts/observe-omada-uplink.py \
  --switch-mac 02-00-00-00-AA-01 \
  --port 3 \
  --ap-mac 02-00-00-00-A0-01 \
  --ap-ip 192.0.2.10 > /path/to/observations/ap1-uplink.json.tmp
mv /path/to/observations/ap1-uplink.json.tmp /path/to/observations/ap1-uplink.json
```

- Switch TX octets map to AP RX; switch RX octets map to AP TX.
- Totals include any wired clients plugged into the Nighthawk's downstream LAN
  ports.
- Stale (> 75 s), out-of-order, or counter-reset samples clear the baseline
  rather than producing traffic spikes.

## Omada 6.3 `ApWlanInformData` wire contracts

Observed directly against Omada Controller 6.3:

- `wSettings_{2G,5G,6G}.txR` must contain a decimal point (for example
  `"688.0Mbps"`, `"5765.0Mbps"`, `"11529.0Mbps"`); integer strings trigger a
  controller string-slicing exception.
- `wSettings_{2G,5G,6G}.txPower` must end with a 3-character unit suffix
  (`"25dBm"`, `"23dBm"`).
- `ssidStats_{2G,5G,6G}` entries must include integer `id` (populated from
  provisioned `SET_REQUEST` `ssid_id`, defaulting to `0`).
- `lanInfo.rate` emits integral values without a decimal suffix (`"10000"`, not
  `"10000.0"`) to avoid Omada topology parsing errors.
- `uplinkPortStatus` must be a JSON array, not a JSON object.

## Controller record repair note

Always save radio settings through the full Omada UI form rather than partial
API `PUT` bodies. A partial radio save can store `channel_width: "null"` in the
controller database and cause device-grid errors; recovering requires removing
the corrupted device record (or forgetting the AP once responsive) and letting
the shim rediscover and re-adopt cleanly.
