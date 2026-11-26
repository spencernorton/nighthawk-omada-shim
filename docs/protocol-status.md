# Protocol Support Matrix

This table tracks **implementation status**, not merely known numeric message
identifiers.

| Family | Status | Notes |
| --- | --- | --- |
| Discovery | ✅ | Site-scoped UDP discovery implemented |
| Pre-adopt | ✅ | `adoptPort` honored |
| Pre-connect | ✅ | First adoption and `rebuild=1` managed reconnect |
| Device verification | ✅ | Legacy V2 `cipherType=5` branch |
| System verification | ✅ | Mutual auth checked before success |
| Device negotiation | ✅ | Conservative AP component map |
| System negotiation | ✅ | Config/version metadata consumed |
| Initial sync result | ✅ | ACK validated |
| Inform | 🟡 | Device and wired LAN telemetry; active hostapd clients enriched with DHCP/openNDS metadata; OpenWrt radio/SSID metrics; and stock-firmware Netgear tri-band radio, main-SSID, and attributable wireless-client telemetry via SOAP. Netgear reports real used memory as `100 - NewMemoryUtilization` and omits `cpuUti` because `NewCPUUtilization` is load-average×100; unavailable router metrics never fall back to container host values. Client `down`/`up` counters are always numeric; Omada-required `0` placeholders represent unavailable internal observations |
| SET | 🟡 | Envelope/version ACKs plus parsed AP domains; unsupported keys or actionable configuration without a suitable port return local error instead of fake success; common controller defaults such as `ssh`, `snmp`, `lldp`, `ipGroup`, `ipv6Group`, `lanSetting`, `logSetting`, and scheduler/mac-filter globals are accepted as passive when they do not require local changes |
| WLAN/radio config | 🟡 | OpenWrt UCI adapter for basic radios and PSK SSIDs; Netgear supports its main-SSID/numeric-channel subset and explicitly rejects unsupported changes |
| SSID VLAN config | 🟡 | Opt-in UCI network interface mapping; dynamic VLAN/Option82 remain rejected unless implemented |
| Management VLAN config | 🟡 | Opt-in UCI device remapping via explicit local target variables |
| Client operations | 🟡 | Reconnect/deauth through hostapd `ubus`; block/unblock and rate-limits through nftables bridge policy |
| LED config | 🟡 | Optional sysfs brightness adapter for `led.enable`; optional trigger adapter for `led.locate`; `wifiControlLed` remains rejected |
| FORGET | ✅ | `FORGET_REQUEST` and no-reset variant are ACKed and clear local reconnect state |
| GET | 🟡 | Handler replies with correlated `GET_RESPONSE` and unsupported-key metadata |
| NOTIFY | 🟡 | Handler replies to v1/v2 notify requests unless `nre=1`; payload-specific handlers are not implemented |
| REPORT | 🚧 | ECSP identifier and `Report.reportData` envelope are known. AP client report protobuf DTOs were identified (`MonitorMessageDTO`, `ComponentDTO`, `ApClientReportDTO`, `WirelessClientDTO`), but the exact `reportData` string serializer used by device-side REPORT is not implemented yet. |
| Upgrade | 🚧 | Not implemented |
| File transfer | 🚧 | Not implemented |
| Remote terminal | 🚧 | Not implemented |
| Radio telemetry | 🟡 | Basic OpenWrt wireless settings from `ubus`; aggregate `radioTraffic_*` from hostapd bytes/packet counters where available; Netgear per-band SOAP state with bounded stale-on-error reuse |
| SSID telemetry | 🟡 | OpenWrt SSID/client counts, BSSID in Omada MAC format, optional interface counters, and hostapd traffic counters; detailed Netgear main-SSID counts require an exact known SSID match and exclude guest, wired, and unknown-SSID records, except for the single-band EAP110 v1 fallback below |
| Client telemetry | 🟡 | Active hostapd station RSSI/SNR/rate/traffic enriched with DHCP IP/hostname and openNDS portal state; Netgear emits attributable wireless clients only, with the single-band EAP110 v1 fallback described below. Client `down`/`up` counters are always numeric; unknown internal values use Omada-required `0` placeholders, while measured zero and real counters are preserved |
| Captive portal | 🟡 | openNDS enforcement, free-policy walled garden, TP-Link EAP External Portal query redirects, `clientConfig.unauth`, and client-state reporting are available on OpenWrt; hosted portal UI and Controller `/hotspot/extPortal/auth` submission are external to the agent |
| Mesh | 🚧 | Not implemented |
| Switch profile | 🚧 | Not implemented |
| Gateway profile | 🚧 | Not implemented |
| OLT profile | 🚧 | Not implemented |

## Capability policy

A protocol component should not be added to the advertised component map merely
because its name/version is known. It should be advertised only after the agent
can safely process the controller behavior that enabling the component causes.

EAP770/EAP773 negotiation keeps required tri-band radio descriptors but does
not advertise MLO, mesh, roaming, DFS, or cluster behavior without southbound
support. `supportSsidNum` follows the actual platform limit rather than the
controller template.

For Netgear, an unsupported member makes the overall SET fail even when
supported operations are applied. Partial changes and accumulated error
reasons are retained. Channel Auto is successful only as an idempotent match;
changing a fixed channel to Auto is rejected. Dynamic VLAN, VLAN pools, and
DHCP Option 82 are explicitly rejected. If any per-band security intent is
invalid, SSID/PSK writes are skipped on every band rather than partially
applying shared wireless credentials.

Netgear does not generally infer missing client band, SSID, rate, or signal
fields. The only attribution exception is the intentional single-band EAP110
`GetAttachDevice` v1 fallback: bandless wireless records use the sole
configured band and its main SSID, including client counts. Tri-band and
otherwise ambiguous records remain unattributed. `OMADA_NETGEAR_STALE_TTL` is
the end-to-end maximum cache age across the adapter and wireless-inform layers,
not a new stale window at each layer; expired data is not returned as current.

## Netgear device telemetry and LAN topology

Netgear real used memory is `100 - NewMemoryUtilization`; measured zero is
preserved, while invalid, failed, or stale-expired values omit `memUti`. No container
host CPU or memory fallback occurs. Netgear omits `cpuUti` because
`NewCPUUtilization` is load-average×100, not CPU utilization. OpenWrt host
CPU/memory metrics remain unchanged.

Isolated Omada `6.3.0.111` qualification covered fresh and omitted memory
values, stale expiry, and managed reconnect. Omada retains the last displayed
`memUti` when later informs omit it, so the retained display is historical and
must not be interpreted as a fresh measurement.

For wired topology, integral-valued `lanInfo.rate` values use integer strings
(`"10000"`, not `"10000.0"`), avoiding Omada 6.3 `NumberFormatException`;
non-integral rates remain unchanged.

## MAC serialization policy

The agent keeps MAC addresses internally in normalized lower-case colon form for
comparison and merging. Any MAC emitted toward Omada is converted at the
boundary to `AA-BB-CC-DD-EE-FF`; this includes ECSP headers, `mainMac`, client
stats, SSID BSSID values, RADIUS Calling/Called-Station-Id values, and openNDS
External Portal redirect parameters.
