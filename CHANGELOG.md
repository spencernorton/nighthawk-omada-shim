# Changelog

All notable project changes will be documented in this file.

## Unreleased

## 0.9.1 - 2026-11-25

- Report explicit per-SSID VLAN 1 as unsupported on stock NETGEAR routers.
  A request containing an unsupported VLAN skips shared SSID and passphrase
  writes across all bands. Zero or omitted VLAN IDs retain untagged behavior.

## 0.9.0 - 2026-11-25

- Optionally read primary channels and negotiated Ethernet uplink speed and
  duplex from the stock RS700S dashboard using its enrolled certificate.
  Passive radio observations continue to supply channel utilization and
  dedicated switch counters supply current traffic rates.
- Use the optional physical LAN MAC to count stations on their confirmed
  serving AP. A wired or foreign association immediately removes an earlier
  wireless entry. Returning to a previous channel requires fresh airtime
  observations for that channel.

## 0.8.0 - 2026-11-25

- Read a second independent radio receiver when configured. Operating channels
  and advertised busy airtime use the original observation timestamps. A channel
  change invalidates airtime measured on the previous channel.

## 0.7.0 - 2026-11-25

- Resolve automatic RS700 radio channels from fresh observations of the exact
  BSSID. Report advertised BSS Load as total channel utilization. Omada can
  show a total without assigning any airtime to interference or TX/RX frames.
- Optionally use the dedicated upstream switch port’s cumulative byte counters for
  wired AP rates. Stale samples and baseline resets do not create spikes.
- Encode SOAP parameters as XML text so credentials and WLAN names with
  reserved characters are transmitted accurately.

## 0.6.0 - 2026-11-19

### Fixed

- Netgear `deviceInfo` no longer reports the container host's CPU or memory as router
  telemetry. A cached read-only `DeviceInfo.GetSystemInfo` call supplies real
  used memory as `100 - NewMemoryUtilization`, because Netgear reports
  free/buffer/cache percentage; measured zero is retained, while invalid or
  stale-expired values omit `memUti` without a container host fallback.
  `NewCPUUtilization` is load-average×100, not CPU utilization, so Netgear omits
  `cpuUti`. Fixed physical/flash capacity fields are ignored, and OpenWrt host
  metrics remain unchanged.
- Serialized integral-valued `lanInfo.rate` values without a decimal suffix
  (`"10000"`, not `"10000.0"`), while preserving non-integral rates, to prevent
  the Omada 6.3 topology `NumberFormatException` found during lab qualification.

### Validation

- The real-memory branch passed 267 tests and an isolated lab against actual
  Omada Controller `6.3.0.111`: discovery/adoption, 159 informs (83 with
  `memUti=39`, 76 with `memUti` omitted), stale expiry, and managed reconnect
  with 38 informs. No `NullPointerException`, `NoSuchElementException`, or
  `StringIndexOutOfBoundsException` occurred.
- Omada retains the last displayed `memUti` after later informs omit it; that
  retained display is not a current measurement. These results are isolated-lab
  qualification only, not production deployment. Production acceptance of the
  separate v0.5.1 hotfix remains independent.

## 0.5.1 - 2026-11-19

### Fixed

- Restored numeric client `down`/`up` fields on every Omada inform. Unknown
  internal counters use the Omada-required `0` wire placeholder, while measured
  zero and real counters remain unchanged. This fixes the Omada 6.3
  `DEVICE_INFORM` null-pointer regression caused by v0.5.0 counter omission.

## 0.5.0 - 2026-11-18

### Added

- Parsed additional recorded Netgear platform fields (`NewStatus`, `NewRegion`,
  `NewWPAEncryptionModes`, and client `ConnAPMAC`) while preserving explicit
  absence when the router does not provide them.

### Changed

- Isolated heartbeat files by device MAC by default
  (`/tmp/open-omada-heartbeat-<12-lowercase-hex>.json`). The `--healthcheck`
  probe now also requires the heartbeat MAC to match `OMADA_DEVICE_MAC`, so one
  agent cannot make another agent's container appear healthy.
- Kept EAP770/EAP773 negotiation conservative: required tri-band radio
  descriptors remain, but MLO, mesh, roaming, DFS, and cluster support are not
  advertised without southbound support. `supportSsidNum` continues to follow
  the actual platform limit (one for the Netgear RS700S integration).
- Made unsupported configuration failures explicit. Actionable configuration
  without a platform or command port is rejected, and Netgear rejects
  unsupported radio, WLAN, portal, client-operation, and LED changes instead of
  acknowledging them. Fixed-to-Auto channel requests now fail unless Auto is
  already active; supported operations may still be applied, but the overall
  SET fails and partial changes and accumulated error reasons are retained.
- Made client counter availability explicit internally and preserved measured
  zero and real counters during metadata merges. The v0.5.0 wire projection
  incorrectly omitted unknown `down`/`up` counters; Omada 6.3 requires numeric
  fields, corrected in 0.5.1.

### Fixed

- Hardened Netgear SOAP parsing for namespaced `GetAttachDevice2` responses,
  case-insensitive band labels, unknown connection types, missing client MACs,
  non-decimal link rates, and out-of-range signal percentages without
  inventing telemetry.
- Corrected Netgear client attribution: wired, unknown-band, and invalid-MAC
  records no longer enter EAP wireless informs; detailed records with unknown
  radios or SSIDs are not defaulted to 2.4 GHz or the main SSID; and
  unavailable link rates stay absent. The sole attribution exception is the
  intentional single-band EAP110 `GetAttachDevice` v1 fallback: bandless
  wireless records use the sole configured band and its main SSID, including
  client counts. Tri-band and otherwise ambiguous records remain unattributed;
  detailed main-SSID counts still require an exact known SSID match.
- Prevented partial Netgear WLAN security writes. Dynamic VLAN, VLAN pools,
  and DHCP Option 82 are explicitly rejected, and any invalid per-band
  security intent skips SSID/PSK writes on every band.
- Bounded all layered Netgear cache reuse by `OMADA_NETGEAR_STALE_TTL` as an
  end-to-end maximum age, not a separate allowance at each layer. Once that
  window expires, the wireless projection returns no payload rather than
  serving stale radio and client counts indefinitely.

## 0.4.0 - 2026-11-14

### Fixed

- Eliminated both recurring 3-second Omada Controller 6.3 `server.log`
  `NullPointerException` traces during EAP informs:
  - `WirelessInfo.getBusyUtil()` (`anomaly-core` `health.b.a:122`) by populating
    integer radio utilization fields (`txUti`, `rxUti`, `interUti`, `busyUti`).
  - `SsidStats.getId().longValue()` (`monitor-statistic` `port.a.i.e.a:135`) by
    tracking provisioned `ssid_id` per band from `SET_REQUEST` and emitting an
    integer `id` in `ssidStats_{2G,5G,6G}`.
- Matched Omada Controller 6.3 `ApWlanInformData` (`j.class`) string contracts
  for tri-band radio telemetry (`txR` decimal `"<int>.0Mbps"`, `txPower`
  3-character unit `"<int>dBm"`, normalized numeric channels, `bw`
  `40MHz`/`160MHz`/`320MHz`, `rdMode` `11be`, and per-radio `staNum`).
- Emitted `uplinkPortStatus` as a JSON array alongside `lanInfo` when
  `OMADA_LAN_RATE > 0` so Omada displays the RS700S 10 Gbps Ethernet uplink.
- Preserved `model` in `ManagedState` when saving `SET_REQUEST` configuration
  versions so `SET_REQUEST` updates do not clear model-bound state.

### Added

- True Netgear RS700S hardware uptime reporting via `DeviceInfo.GetSysUpTime`
  wired into `GenericOpenWrtAccessPointProfile` (replacing host container
  `/proc/uptime` when available).
- Thread-safe stale-on-error caching (`OMADA_NETGEAR_STALE_TTL`, default
  `180.0` seconds) in `LazyNetgearAdapter` for radio state, attached clients,
  and router uptime so transient SOAP timeouts or session blips do not drop
  informs.
- Atomic session heartbeat file (`OMADA_HEARTBEAT_FILE`, default
  `/tmp/open-omada-heartbeat.json`) and `open-omada-agent --healthcheck` CLI
  probe for container liveness checks.

## 0.3.0 - 2026-11-14

### Fixed

- Fixed Omada Controller 6.3 `ApClientImage` crash (`IllegalArgumentException:
  Failed to resolve ApClientImage connection, unknown radioId or rids`) that
  aborted `DEVICE_INFORM` client updates whenever wired pass-through (`Ethernet`)
  or `- Guest` (guest/IoT) records were emitted without a valid `rid`. Wired
  pass-through hosts are now excluded from EAP informs so they remain on their
  upstream switch port while wireless clients update cleanly.
- Parsed Netgear `GetAttachDevice2` wireless `ConnectionType` suffixes
  (`2.4GHz - Guest`, `5GHz - Guest`, `6GHz - Guest`) into true radio bands and
  defaulted v1 wireless fallback records to `2.4G` so wireless EAP informs
  always carry `rid`.
- Formatted ECSP `deviceInfo.upTime` as `<days> days <HH>:<MM>:<SS>` to match
  Omada Controller's `StringTokenizer` parser (`aa.k`), eliminating recurring
  `NoSuchElementException` errors and populating live AP uptime.

### Added

- Shared TTL caching (`OMADA_NETGEAR_CLIENT_TTL`, default `30.0` seconds) on
  `LazyNetgearAdapter.read_clients()` across client and wireless informs,
  reducing synchronous 12–18 s `GetAttachDevice2` SOAP load from ~20 calls/min
  to 2 calls/min.
- Negotiated PHY link rate projection (`Linkspeed` Mbit/s → ECSP `rxR`/`txR`
  Kbit/s) and `GetAttachDevice2` device fingerprint fields (`DeviceTypeNameV2`,
  `DeviceBrand`, `DeviceModel`).
- Model-bound `ManagedState` persistence so changing `OMADA_DEVICE_MODEL`
  (e.g. `EAP110` → `EAP770`) invalidates stale reconnect state automatically.
- Continuous integration checks running `compileall`, `pytest`, and `ruff check`.

## 0.2.2 - 2026-11-13

### Fixed

- SOAP session expiry no longer degrades long-running informs: a `401`
  from the router triggers one re-login and retry (including the
  detailed client poll), instead of failing every later poll.

## 0.2.1 - 2026-11-13

### Added

- True wired/wireless client labeling: client state carries the medium
  from `GetAttachDevice2`; wired clients are reported without SSID,
  radio, or RSSI markers so the controller's `wireless` flag matches
  the router's true connection type. Verified live on an isolated AP.

## 0.2.0 - 2026-11-13

First formal release of the Nighthawk fork: the Netgear RS700 mesh runs
as a native Omada EAP (ECSP northbound, Genie SOAP southbound),
with honest rejection of anything the router cannot apply.

### Added (fork)

- Netgear Genie SOAP southbound for the RS700: per-band state, clients,
  fixed-channel and guest setters with same-value skip semantics.
- Container deployment packaging (`Dockerfile`, host networking, persisted `/state` adoption volume, environment-variable credentials).
- Tri-band `EAP770`/`EAP773` device profile with controller-template
  radio caps and deviceMisc (SSID count and mesh stay conservative so
  the profile never promises what the southbound cannot apply).
- Per-band client attribution via `GetAttachDevice2`: `ssidStats`
  counts main-SSID clients per band and the client list carries real
  SSID and radio per client.

### Added

- AP `SET_REQUEST` domain parsing for radios, SSIDs, VLAN, portal policy, LED,
  and Wi-Fi control LED keys.
- OpenWrt UCI reconciliation for supported radio/SSID/PSK and opt-in SSID VLAN
  configuration.
- Platform capability detection to prevent unsupported AP features from being
  acknowledged as applied.
- DHCP lease backed client inform reporting.
- Captive portal session lifecycle, nftables policy rendering, and minimal
  RADIUS PAP authentication primitives.
- OpenWrt wireless telemetry for `wSettings_*` and `ssidStats_*` inform keys.
- `FORGET_REQUEST` and `FORGET_REQUEST_NO_RESET` handling.
- Optional sysfs LED brightness adapter for `led.enable`.

### Changed

- Unsupported AP `SET_REQUEST` keys now return a local config error instead of
  being silently acknowledged.

### Documentation

- Reworked ECSP protocol and lifecycle documentation around Mermaid sequence diagrams for clearer transport, ordering, authentication, configuration, reconnect, and managed-rediscovery flows.

## 0.1.0-alpha.1 - 2026-08-22

Initial Open Omada public-alpha preparation.

### Included

- ECSP V2 length-prefixed JSON framing.
- Site-scoped UDP discovery.
- TLS management channel.
- Legacy Device Account mutual verification.
- Device/system negotiation and initial sync.
- Conservative AP component advertisement.
- Periodic managed informs.
- Absolute and incremental `SET_REQUEST` acknowledgements.
- Persistent non-secret reconnect state.
- Direct managed reconnect and stale-context managed rediscovery.
- Python package/CLI layout, tests, CI, and protocol documentation.
