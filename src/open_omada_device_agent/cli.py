"""Command-line entry point for Open Omada Device Agent."""
from __future__ import annotations

import argparse
import logging

from . import __version__, discovery
from .bootstrap import AgentSettings, build_runtime
from .util.heartbeat import check_heartbeat


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-omada-agent",
        description="Experimental device-side Omada ECSP V2 agent",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--once",
        action="store_true",
        help="send one discovery and exit after a short receive window",
    )
    parser.add_argument(
        "--dump-tx",
        action="store_true",
        help="log outgoing and incoming ECSP JSON payloads",
    )
    parser.add_argument(
        "--no-adopt",
        action="store_true",
        help="stop at PRE_ADOPT_REQUEST and do not open the management channel",
    )
    parser.add_argument(
        "--clear-state",
        action="store_true",
        help="delete local managed-reconnect state and force discovery for this run",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="verify session heartbeat freshness and exit 0 (healthy) or 1 (unhealthy)",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("open_omada.cli")

    if args.healthcheck:
        settings = AgentSettings.from_environment()
        max_age = max(60.0, settings.inform_interval * 6.0, settings.netgear_client_ttl * 2.0)
        ok, detail = check_heartbeat(
            settings.heartbeat_file,
            max_age_s=max_age,
            expected_mac=settings.mac,
        )
        if not ok:
            log.error("healthcheck failed: %s", detail)
            raise SystemExit(1)
        log.debug("healthcheck ok: %s", detail)
        raise SystemExit(0)

    try:
        settings = AgentSettings.from_environment()
        settings.validate()
        runtime = build_runtime(settings)
    except RuntimeError as exc:
        log.error("configuration error: %s", exc)
        raise SystemExit(2) from exc

    if args.clear_state:
        if runtime.state_repository.clear():
            log.warning("Cleared local managed reconnect state; forcing discovery/adoption")
        else:
            log.info("No local managed reconnect state existed; forcing discovery/adoption")

    try:
        discovery.run(
            services=runtime,
            once=args.once,
            dump_tx=args.dump_tx,
            no_adopt=args.no_adopt,
            force_discovery=args.clear_state,
        )
    except KeyboardInterrupt:
        log.info("Stopped")
    except Exception:
        log.exception("Fatal ECSP state-machine error")
        raise SystemExit(1)
