"""Atomic local liveness heartbeat for container/process health probes."""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from ..shared.domain import MacAddress

log = logging.getLogger("open_omada.heartbeat")


def default_heartbeat_path(mac: str) -> Path:
    """Return a per-device heartbeat path derived from the canonical MAC."""
    identity = MacAddress(mac).value.replace(":", "")
    return Path(f"/tmp/open-omada-heartbeat-{identity}.json")


def write_heartbeat(
    path: Path | None,
    *,
    phase: str,
    mac: str,
    controller_host: str,
    seq: int | None = None,
    now: Callable[[], float] = time.time,
) -> None:
    """Atomically write current session heartbeat; never raises on I/O errors."""
    if path is None:
        return
    payload = {
        "phase": phase,
        "mac": mac,
        "controller_host": controller_host,
        "seq": seq,
        "pid": os.getpid(),
        "updated_at": round(float(now()), 3),
    }
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
        os.replace(tmp_path, path)
    except OSError as exc:
        log.warning("could not update heartbeat %s: %s", path, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def check_heartbeat(
    path: Path | None,
    *,
    max_age_s: float,
    expected_mac: str | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[bool, str]:
    """Validate heartbeat readability, optional device identity, and freshness."""
    if path is None:
        return False, "heartbeat file disabled"
    if not path.exists():
        return False, f"heartbeat file missing: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"heartbeat unreadable: {exc}"
    if not isinstance(data, dict) or "updated_at" not in data:
        return False, "heartbeat missing updated_at"
    if expected_mac is not None:
        try:
            expected = MacAddress(expected_mac).value
        except ValueError:
            return False, f"configured MAC is invalid: {expected_mac!r}"
        try:
            actual = MacAddress(str(data.get("mac", ""))).value
        except ValueError:
            return False, "heartbeat MAC is missing or invalid"
        if actual != expected:
            return False, f"heartbeat MAC mismatch: expected={expected} actual={actual}"
    try:
        updated_at = float(data["updated_at"])
    except (TypeError, ValueError):
        return False, "heartbeat updated_at is not numeric"
    age = float(now()) - updated_at
    if age > max_age_s:
        return (
            False,
            f"heartbeat stale: age={age:.1f}s > max_age={max_age_s:.1f}s (phase={data.get('phase')})",
        )
    return True, f"healthy: phase={data.get('phase')} age={age:.1f}s seq={data.get('seq')}"
