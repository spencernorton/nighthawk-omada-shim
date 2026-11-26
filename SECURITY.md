# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub:
**[Report a vulnerability](https://github.com/spencernorton/nighthawk-omada-shim/security/advisories/new)**.
Do not open a public issue, and do not include real credentials, packet captures
with authentication tokens, router passwords, real hardware MACs/BSSIDs, or
personal paths in the report — a description and a minimal reproduction are
enough.

There is no e-mail address for security reports; the advisory form is the
only channel, and it is the one that is monitored. You will get an
acknowledgement within a week. Fixes ship as a tagged release; the advisory
is published once the release is out, and credits you unless you ask
otherwise.

## Supported versions

Only the latest tagged release is supported. Nighthawk Omada Shim has no LTS line.

## Scope

In scope: this repository's code, observer scripts, and the container artefacts
it ships.
Out of scope: TP-Link Omada controllers, NETGEAR router firmware, third-party
libraries, and deployments the maintainer does not operate.

## What Nighthawk Omada Shim does with credentials and data

Understanding the trust model helps you judge what is and is not a finding:

- **Credentials live in environment variables only.** `OMADA_DEVICE_PASSWORD`
  and `OMADA_NETGEAR_PASSWORD` are read from the process environment at runtime
  and are never persisted to the managed-state JSON file or heartbeat file.
- **Certificate verification is configurable.** Omada ECSP management TLS
  verification is opt-in (`OMADA_TLS_VERIFY=true`, `OMADA_TLS_CA_FILE`) because
  controllers commonly ship self-signed certificates. The optional Netgear stock
  dashboard reader requires an explicit DER SHA-256 certificate pin
  (`OMADA_NETGEAR_DASHBOARD_CERT_SHA256`) and refuses unpinned sessions.
- **No external telemetry leaves your LAN by default.** All traffic stays
  between the shim, the configured Omada controller, and the configured Netgear
  router unless you explicitly set `OMADA_DEVICE_IP=auto`.
- **Local state** lives under `/state/agent-state.json` (or `OMADA_STATE_FILE`)
  and `/tmp/open-omada-heartbeat-<mac>.json`. Restrict directory permissions on
  the host volume (for example mode `0700`).
