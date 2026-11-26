# Configuration Reference

Configuration is read from `OMADA_*` environment variables. `python-dotenv`
loads a local `.env` file automatically for development and lab use.

Copy the template:

```bash
cp .env.example .env
```

## Controller transport

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_CONTROLLER_HOST` | required | Controller hostname or IP |
| `OMADA_DISCOVERY_PORT` | `29810` | UDP discovery port |
| `OMADA_MANAGE_PORT` | `29814` | Default ECSP V2 management port |
| `OMADA_LOCAL_DISCOVERY_PORT` | `0` | Local UDP source port; `0` lets the OS choose |
| `OMADA_DISCOVERY_INTERVAL` | `5` | Discovery interval in seconds |
| `OMADA_TCP_TIMEOUT` | `15` | Management socket timeout |
| `OMADA_INFORM_INTERVAL` | `3` | Managed inform interval |
| `OMADA_RECONNECT_DELAY` | `3` | Delay between direct reconnect attempts |
| `OMADA_MANAGED_RECONNECT_ATTEMPTS` | `3` | Failures before managed rediscovery |

## Controller and site routing

| Variable | Description |
| --- | --- |
| `OMADA_CONTROLLER_ID` | Logical controller identifier used by the ECSP management session |
| `OMADA_SITE_ID` | Site-scoped discovery target and preferred External Portal `site` parameter |
| `OMADA_DEST_OMADAC_ID` | Low-level discovery destination override when no Site ID is used |

For the tested Controller 6.2 family, Controller IDs are typically 32
characters and Site IDs 24 characters.

## Device identity

| Variable | Default |
| --- | --- |
| `OMADA_DEVICE_MAC` | `02:00:00:00:00:01` |
| `OMADA_DEVICE_NAME` | `OpenOmada-AP` |
| `OMADA_DEVICE_MODEL` | `EAP110` |
| `OMADA_DEVICE_MODEL_VERSION` | `4.0` |
| `OMADA_DEVICE_HARDWARE_VERSION` | `4.0` |
| `OMADA_DEVICE_FIRMWARE_VERSION` | `5.0.4` |
| `OMADA_CUSTOMIZE_REGION` | `841` |
| `OMADA_DEVICE_IP` | `0.0.0.0` |

`OMADA_DEVICE_IP=auto` enables a best-effort external public-IP lookup. This is
off by default so the agent does not unexpectedly contact a third-party service.

## Device Account authentication

| Variable | Description |
| --- | --- |
| `OMADA_DEVICE_USERNAME` | Optional explicit Device Account username |
| `OMADA_DEVICE_PASSWORD` | Device Account password; required for the current verification path |
| `OMADA_DEVICE_CIPHER_TYPE` | Current implementation expects `5` |

If the username is omitted, the agent requests it from the controller during
pre-connect.

Never commit `.env`.

## TLS

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_TLS_VERIFY` | `false` | Verify the controller's TLS certificate |
| `OMADA_TLS_CA_FILE` | empty | Optional custom CA file |

For a trusted deployment:

```dotenv
OMADA_TLS_VERIFY=true
OMADA_TLS_CA_FILE=/etc/open-omada/controller-ca.pem
```

## Uplink telemetry

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_LAN_RATE` | `100` | Reported wired link rate in Mbit/s; integral values omit the `lanInfo.rate` decimal suffix for Omada topology parsing, while non-integral values are preserved |
| `OMADA_LAN_DUPLEX` | `1` | Duplex value used by the reference profile |
| `OMADA_LAN_PORT` | `LAN` | Uplink port label |

## AP platform features

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_PLATFORM` | `auto` | `auto`, `openwrt`, or `generic` capability detection |
| `OMADA_RADIO_BANDS` | `2g` | Comma-separated supported AP bands: `2g,5g,5g2,6g` |
| `OMADA_MAX_SSIDS` | `4` | Manual upper bound for SSIDs the platform adapter will accept. On OpenWrt, `iw list` can reduce this automatically when the radio does not support multiple AP interfaces. |
| `OMADA_CAP_WLAN` | auto on OpenWrt with `uci` | Enable WLAN/radio UCI reconciliation |
| `OMADA_CAP_WPA2_PSK` | auto on OpenWrt with `uci` | Accept WPA2-PSK WLANs |
| `OMADA_CAP_WPA3_PSK` | `false` | Accept WPA3-PSK WLANs |
| `OMADA_CAP_SSID_VLAN` | `false` | Accept SSID VLAN mapping |
| `OMADA_CAP_DYNAMIC_VLAN` | `false` | Accept dynamic VLAN requests |
| `OMADA_CAP_MANAGEMENT_VLAN` | `false` | Accept management VLAN requests |
| `OMADA_CAP_PORTAL` | auto with OpenWrt + openNDS | Enable portal WLAN acceptance; explicit `false` disables portal acceptance |
| `OMADA_CAP_DHCP_TRACKING` | auto on OpenWrt with `ubus` | Include observed DHCP lease clients |
| `OMADA_CAP_OPTION82` | `false` | Accept DHCP Option 82 WLAN settings |
| `OMADA_CAP_LED` | path-based | Enable sysfs LED brightness/trigger writes |
| `OMADA_CAP_CLIENT_OPERATIONS` | auto on OpenWrt with `ubus` | Enable supported client control commands |
| `OMADA_CAP_CLIENT_RATE_LIMITS` | `false` | Enable nftables client rate-limit enforcement |

## OpenWrt startup bootstrap

The agent runs an idempotent OpenWrt bootstrap before ECSP discovery when
`OMADA_OPENWRT_BOOTSTRAP=true` and the detected platform is OpenWrt. This is
where lab-only manual setup belongs.

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_OPENWRT_BOOTSTRAP` | `true` | Enable startup self-healing for OpenWrt prerequisites |
| `OMADA_OPENWRT_BOOTSTRAP_LAN` | `true` | Ensure the LAN bridge can exist even with only Wi-Fi ports |
| `OMADA_OPENWRT_LAN_INTERFACE` | `lan` | UCI network interface used by Omada WLANs |
| `OMADA_OPENWRT_LAN_BRIDGE` | `br-lan` | UCI bridge device used by OpenWrt AP interfaces and openNDS |
| `OMADA_OPENWRT_LAN_IPADDR` | `192.168.1.1/24` | LAN address used only when the bootstrap must create a missing LAN interface |
| `OMADA_OPENWRT_BOOTSTRAP_OPENNDS` | `true` | Enable and start openNDS when installed |
| `OMADA_OPENNDS_GATEWAY_PORT` | `2050` | openNDS local gateway port |
| `OMADA_OPENNDS_GATEWAY_NAME` | device name | openNDS gateway name; empty uses `OMADA_DEVICE_NAME` |
| `OMADA_SITE_NAME` | empty | Human-readable fallback for External Portal redirects when no site ID is available |
| `OMADA_OPENWRT_ENABLE_WAN_MANAGEMENT` | `false` | Lab-only opt-in to open SSH, LuCI HTTP, and LuCI HTTPS from the WAN zone |
| `OMADA_OPENWRT_WAN_ZONE` | `wan` | Firewall zone used by the WAN management opt-in rules |

The LAN bootstrap sets `bridge_empty=1` on the bridge device. This is required
on Wi-Fi-only OpenWrt devices where `br-lan` otherwise does not exist until a
radio interface is already attached, which prevents hostapd/openNDS from
starting cleanly.

## OpenWrt targets

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_MANAGEMENT_VLAN_INTERFACE` | empty | UCI network interface to update for management VLAN |
| `OMADA_MANAGEMENT_VLAN_DEVICE` | empty | Base OpenWrt device, for example `br-lan` |
| `OMADA_HOSTAPD_UBUS_IFACE` | empty | hostapd ubus object suffix for reconnect/deauth, for example `wlan0` |
| `OMADA_CLIENT_BLOCK_INTERFACE` | empty | Bridge/interface used by nftables client block rules |
| `OMADA_CLIENT_RATE_LIMIT_INTERFACE` | empty | Bridge/interface used by nftables per-client rate-limit rules |
| `OMADA_PORTAL_INTERFACE` | empty | Fallback nftables-only portal interface; unused when openNDS is installed |
| `OMADA_PORTAL_REDIRECT_PORT` | `8080` | Fallback nftables-only local HTTP redirect port; unused when openNDS is installed |

Unsupported controller keys are intentionally rejected with a local
`SET_RESPONSE.errcode=1`. Actionable platform or device-command configuration
also fails when no corresponding port is configured; it is never acknowledged
merely because an adapter is absent.

Netgear reconciliation accepts passive defaults, idempotent state, and the
supported main-SSID/numeric-channel operations, but rejects unsupported radio,
WLAN, security, portal, client-operation, and LED changes. Stock NETGEAR
accepts an omitted or zero per-SSID `vlanId` for untagged service. Any
positive VLAN ID, including 1, fails the request and suppresses shared SSID
and passphrase writes on all bands. An independent supported channel change
in the same request can still apply. Dynamic VLAN
(`dyVlanMode`), VLAN pools (`vlanPoolIds`), and enabled DHCP Option 82
(`dhcpOp82`) are explicitly rejected. If any per-band security intent is
invalid, all SSID/PSK writes are skipped on every band; no band receives a
partial shared-name/key update. Requesting channel Auto is an idempotent no-op
only when the router is already in Auto mode; a fixed-to-Auto change is
unsupported. Supported operations can still be applied when another part of
the request is unsupported, but the overall SET then fails, retains
partial-change state, and reports all available error reasons.

## Captive portal on OpenWrt

Use `openNDS` as the OpenWrt captive portal engine. The built-in nftables
adapter remains only as a fallback for lab setups without openNDS.

For OpenWrt 25 snapshots:

```bash
apk update
apk add opennds dnsmasq-full conntrack
```

For older OpenWrt package feeds:

```bash
opkg update
opkg install opennds dnsmasq-full conntrack
```

Minimal UCI example:

```bash
uci set opennds.@opennds[0].enabled='1'
uci set opennds.@opennds[0].gatewayinterface='br-lan'
uci set opennds.@opennds[0].gatewayport='2050'
uci set opennds.@opennds[0].gatewayfqdn='disable'
uci commit opennds
/etc/init.d/opennds restart
```

With openNDS installed, the agent:

- reports portal client state from `ndsctl json`;
- applies `portalFreePolicyConfig` URL rules as openNDS walled-garden FQDNs;
- applies `portalFreePolicyConfig` IP rules as openNDS preauthenticated user
  rules;
- writes `/usr/lib/opennds/theme_openomada_redirect.sh` and sets
  `login_option_enabled=3` when Omada provides a portal URL through
  `portalConfigList` or a `/portal/...` free-policy URL;
- redirects EAP clients with the TP-Link External Portal query contract:
  `clientMac`, `clientIp`, `t`, `site`, `redirectUrl`, `apMac`,
  `ssidName`, and `radioId`;
- sets `allow_preemptive_authentication=0` so clients use the classic HTTP
  redirect path instead of stopping at the openNDS RFC8910 status page;
- sets `gatewayfqdn=disable` so the openNDS preauth redirect uses the gateway
  IP instead of the local-only `status.client` hostname. This avoids breaking
  captive portal flow on clients that ignore DHCP DNS and use a custom resolver;
- applies `clientConfig.unauth=false` with `ndsctl auth`;
- applies `clientConfig.unauth=true` with `ndsctl deauth`;
- clears conntrack entries for the client IP after deauth when `conntrack` is
  installed;
- does not install its own `inet openomada_portal` table.

The generated ThemeSpec derives `clientMac`, `clientIp`, and `originurl` from
openNDS FAS variables, uses `OMADA_DEVICE_MAC` for `apMac`, falls back to
`iw dev <clientif> info` for SSID/radio detection, and uses `OMADA_SITE_ID` as
the `site` parameter when available. `OMADA_SITE_NAME` is only a fallback. MAC
addresses are emitted in Omada portal form (`AA-BB-CC-DD-EE-FF`), timestamps are
seconds, and query values use form encoding (`+` for spaces).

## DHCP/client tracking

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_DHCP_LEASE_FILE` | `/tmp/dhcp.leases` | dnsmasq lease file used to report real IP/hostname client data |

If the lease file is absent, DHCP enrichment is skipped. DHCP leases and
openNDS sessions are metadata sources only: production inform reports a client
only when the same MAC is currently present in the latest hostapd association
list. This prevents disconnected clients from lingering as active Omada clients.

## LED control

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_LED_BRIGHTNESS_PATH` | empty | sysfs brightness file for `led.enable` |
| `OMADA_LED_ON_VALUE` | `1` | Value written when Controller enables the LED |
| `OMADA_LED_OFF_VALUE` | `0` | Value written when Controller disables the LED |
| `OMADA_LED_TRIGGER_PATH` | empty | sysfs trigger file for `led.locate` |
| `OMADA_LED_LOCATE_TRIGGER` | `timer` | Trigger value while locate is active |
| `OMADA_LED_DEFAULT_TRIGGER` | `none` | Trigger value restored when locate stops |

`wifiControlLed` is parsed but rejected because it represents hardware button
semantics, not the LED brightness/locate state itself.

## State file

The default state file is derived from the device MAC:

```text
.omada-agent-state-020000000001.json
```

Override with `OMADA_STATE_FILE` when needed. The file is Git-ignored by
default.

## Heartbeat and healthcheck

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_HEARTBEAT_FILE` | `/tmp/open-omada-heartbeat-<12-lowercase-hex>.json` | Atomic session heartbeat path derived from `OMADA_DEVICE_MAC`; set an explicit path to override it or an empty value to disable heartbeat writes |

For example, MAC `02:00:00:00:00:01` uses
`/tmp/open-omada-heartbeat-020000000001.json`. This per-device default prevents
co-located agents from overwriting each other's liveness state.

Run `open-omada-agent --healthcheck` (or
`python -m open_omada_device_agent --healthcheck`) to verify that the file is
readable, fresh, and contains the MAC configured by `OMADA_DEVICE_MAC`. A
missing, malformed, stale, or different-device heartbeat exits nonzero. The
maximum accepted age is the greatest of 60 seconds, six inform intervals, and
two Netgear client-cache intervals.

## Netgear Genie SOAP sidecar (`OMADA_SOUTHBOUND=netgear`)

The RS700S southbound requires Netgear stock firmware. There is no supported
RS700S OpenWrt, DD-WRT, FreshTomato, or Merlin path; keep stock firmware unless
that support posture changes.

| Variable | Default | Description |
| --- | --- | --- |
| `OMADA_SOUTHBOUND` | `openwrt` | Set to `netgear` to run against a Netgear Nighthawk RS700 over Genie SOAP |
| `OMADA_NETGEAR_PHYSICAL_MAC` | unset | Physical LAN MAC reported by this AP as `ConnAPMAC`. When set, only confirmed local stations enter its station list and radio/SSID counts. Legacy SOAP rows without an AP identity cannot add or renew a station. |
| `OMADA_NETGEAR_HOST` | empty | Router/AP IP or hostname for HTTPS SOAP (`:443/soap/server_sa/`) |
| `OMADA_NETGEAR_USERNAME` | `admin` | Router admin username |
| `OMADA_NETGEAR_PASSWORD` | empty | Router admin password (pass via secret environment only) |
| `OMADA_NETGEAR_DASHBOARD_CERT_SHA256` | empty | Enable read-only stock dashboard telemetry with the trusted 64-hex SHA-256 of this router’s DER TLS certificate |
| `OMADA_NETGEAR_DASHBOARD_UPLINK` | `WAN` | Physical jack shown in NETGEAR Show Statistics. Accepts `WAN`, `LAN1`–`LAN4` or `LAN 10G` |
| `OMADA_NETGEAR_CLIENT_TTL` | `30.0` | Shared TTL cache in seconds for `GetAttachDevice2` client polls (`0` disables caching) |
| `OMADA_NETGEAR_STALE_TTL` | `180.0` | End-to-end maximum age in seconds for cached Netgear radio/client/uptime/system-memory and wireless-inform data across all layered caches, not an additional allowance per layer (`0` disables stale reuse) |
| `OMADA_NETGEAR_BEACON_FILE` | empty | Version-1 JSON file of BSSID observations from the first receiver |
| `OMADA_NETGEAR_SECONDARY_BEACON_FILE` | empty | Version-1 JSON file published independently by a second receiver |
| `OMADA_NETGEAR_UPLINK_FILE` | empty | Version-1 JSON file of the dedicated switch port’s cumulative byte counters for this AP |

Mount each observation directory read-only so the shim sees atomically replaced files.
Radio observations expire after 300 seconds and uplink counters after 75 seconds.
See [radio and uplink observations](operations.md#rs700-operating-channels-and-aggregate-utilization)
for file producers, counter directions and controller display limits.

With the per-router certificate pin enrolled, a background reader opens the
stock home page through its normal HTTPS authentication challenge. It reuses
that session for Advanced and Show Statistics, with a minimum interval of two
minutes between polls. Router channel and link observations expire after five
minutes. A failed read backs off for ten minutes. If the router rejects the
credential, correct it and restart the agent to resume the reader.

The selected jack supplies physical link speed and duplex. An explicitly
down port reports link down. Until a fresh jack observation is available,
the agent uses the configured LAN values. A newly configured numeric radio
channel takes precedence. For automatic selection the dashboard supplies the
operating channel. Passive BSS Load must match the
radio BSSID, band and operating channel. Current traffic still comes from
the switch counters; the dashboard’s since-startup averages are excluded.

Only attributable wireless Netgear clients enter EAP informs. Wired and
invalid-MAC records are excluded. Detailed records with unknown bands or
SSIDs remain unattributed, and missing rates or signal measurements remain
absent; there is no general inference of those fields. The only attribution
exception is intentional: for a single-band EAP110, when `GetAttachDevice2`
falls back to `GetAttachDevice` v1, bandless wireless records use the sole
configured band and its main SSID, including client counts. Tri-band and
otherwise ambiguous records remain unattributed and are never defaulted to
2.4 GHz or the main SSID. Client `down`/`up` byte counters are always numeric
on the Omada wire; unavailable internal values use Omada's required `0`
placeholder, while measured zero and real counters are preserved.

Netgear system telemetry uses the router's cached `DeviceInfo.GetSystemInfo`
response. Real used memory is `100 - NewMemoryUtilization`; invalid, failed, or
stale-expired values omit `memUti`, and no container host CPU or memory fallback
occurs. Netgear omits `cpuUti` because `NewCPUUtilization` is load-average×100,
not CPU utilization. OpenWrt host CPU/memory metrics remain unchanged. Omada
retains the last displayed `memUti` when later informs omit it; that retained
value is historical, not a current router measurement.

Integral-valued `OMADA_LAN_RATE` settings are emitted in `lanInfo.rate` without
a decimal suffix (for example, `10000.0` becomes `"10000"`), preventing Omada
6.3 topology `NumberFormatException`; non-integral rates remain unchanged.
