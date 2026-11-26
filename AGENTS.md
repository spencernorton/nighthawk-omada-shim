# Nighthawk Omada Shim — Repository Guide

This repository hosts **Nighthawk Omada Shim**, an Apache-2.0 derivative of
Open Omada Device Agent (`adryanalencar/open-omada-device-agent`) focused on
connecting stock-firmware Netgear Nighthawk access points (RS700/RS700S) to a
TP-Link Omada Network Application controller over ECSP.

## Layout

- `src/open_omada_device_agent/adapters/inbound/ecsp/`: ECSP V2 wire framing,
  crypto, and inbound mappers.
- `src/open_omada_device_agent/adapters/outbound/netgear/`: Netgear Genie SOAP
  client, bounded caches, client ownership, stock dashboard reader, passive
  beacon reader, and dedicated switch-port uplink reader.
- `src/open_omada_device_agent/bootstrap/`: composition root (`runtime.py`) and
  settings (`settings.py`).
- `scripts/rs700_beacon_observer.py` & `scripts/observe-omada-uplink.py`:
  optional read-only observation producers.
- `tests/`: unit and replay tests covering ECSP framing, lifecycle, Netgear
  SOAP/dashboard/beacon/uplink adapters, and container CLI healthcheck.

## Checks

Run before opening a pull request:

```bash
python -m compileall -q src tests agent.py
pytest -q
ruff check .
```

## Guardrails

- Never commit real credentials, router passwords, device account passwords,
  real LAN IPs, real hardware MACs/BSSIDs, or private SSIDs. Use RFC 5737
  documentation IP ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`)
  and locally administered MAC addresses (`02:00:00:...`) in tests and docs.
- Never fake-acknowledge unsupported Omada `SET_REQUEST` operations on stock
  Netgear firmware; unsupported intents must fail explicitly.
- Preserve upstream Apache-2.0 attribution in `LICENSE` and `NOTICE`.
- Sign off commits (`git commit -s`).
