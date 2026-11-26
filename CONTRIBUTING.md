# Contributing to Nighthawk Omada Shim

Thanks for your interest. Nighthawk Omada Shim is a small project with one
maintainer, so the process is deliberately light — but a few things are fixed.

## How changes land

Development happens in this repository. Pull requests target `main`; once
CI passes, an accepted pull request is squash-merged, so it lands as one
commit credited to you. A release is a `vX.Y.Z` tag on `main`: the Release
workflow builds the multi-arch container image and publishes it with the tagged
source, and [CHANGELOG.md](CHANGELOG.md) says what changed.

- Keep a pull request to one change, and rebase it onto `main` only.

## Before you start

- **Bugs** — open a [bug report](https://github.com/spencernorton/nighthawk-omada-shim/issues/new/choose).
  A report with reproduction steps, controller/router versions, and a scrubbed
  log excerpt is usually fixed faster than a pull request that arrives without
  one.
- **Features** — open a feature request first. Nighthawk Omada Shim has strong
  opinions about honest capability reporting, never fake-acknowledging
  unsupported Omada `SET` intents, and keeping stock router firmware intact; an
  idea that cuts across them needs a conversation before code.
- **Security** — never in a public issue. Use
  [private vulnerability reporting](https://github.com/spencernorton/nighthawk-omada-shim/security/advisories/new);
  see [SECURITY.md](SECURITY.md).

## Working on the code

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m compileall -q src tests agent.py
pytest -q
ruff check .
```

- Keep all tests offline and deterministic; use RFC 5737 documentation IPs
  (`192.0.2.0/24`) and locally administered MAC addresses (`02:00:00:...`).
- Keep a change to one concern. A pull request that fixes a bug and
  reformats a file is two pull requests.
- Tests: a bug fix carries a regression test; a feature carries the smallest
  test that fails without it.
- Commits carry a `Signed-off-by:` line (`git commit -s`, the Developer
  Certificate of Origin). There is no CLA.
- No secrets, hostnames, real hardware MACs/BSSIDs, private SSIDs, or personal
  paths in the diff — scrub all captures and fixtures before committing.

## Out of scope

So nobody wastes an evening on it, Nighthawk Omada Shim will not accept:

- Vendor firmware images, decompiled vendor binaries, certificates, or
  proprietary assets.
- Silent fake-acknowledgement of Omada features that stock Netgear firmware
  cannot actually apply (such as per-SSID VLANs, captive portal, or mesh).
- Telemetry or external phone-home analytics.

## Pull request checklist

The template asks for what changed, why, and how it was tested, plus a
confirmation that the diff carries no secrets, machine names, real MACs, or
personal paths. Fill it in — it is what the reviewer reads first.

## Licence

By contributing you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE) that covers the project.
