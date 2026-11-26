"""Tests for atomic session heartbeat writing and CLI --healthcheck."""
import json
import os
from pathlib import Path
import subprocess
import sys

from open_omada_device_agent.util.heartbeat import (
    check_heartbeat,
    default_heartbeat_path,
    write_heartbeat,
)


def _cli_environment():
    env = dict(os.environ)
    src = Path(__file__).resolve().parents[1] / "src"
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([str(src), existing] if existing else [str(src)])
    return env


def _run_healthcheck(env, cwd):
    return subprocess.run(
        [sys.executable, "-m", "open_omada_device_agent", "--healthcheck"],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_write_and_check_heartbeat_freshness(tmp_path):
    hb = tmp_path / "heartbeat.json"
    ok, detail = check_heartbeat(hb, max_age_s=45.0, now=lambda: 1000.0)
    assert not ok and "missing" in detail

    write_heartbeat(
        hb,
        phase="managed",
        mac="02:00:00:00:00:01",
        controller_host="192.0.2.8",
        seq=17,
        now=lambda: 1000.0,
    )
    ok, detail = check_heartbeat(hb, max_age_s=45.0, now=lambda: 1015.0)
    assert ok and "phase=managed" in detail and "seq=17" in detail

    ok_stale, detail_stale = check_heartbeat(hb, max_age_s=45.0, now=lambda: 1060.0)
    assert not ok_stale and "stale" in detail_stale


def test_per_device_heartbeat_defaults_are_independent(tmp_path):
    first_mac = "02:00:00:00:01:01"
    second_mac = "02:00:00:00:01:02"
    first_default = default_heartbeat_path(first_mac)
    second_default = default_heartbeat_path(second_mac)

    assert first_default == Path("/tmp/open-omada-heartbeat-020000000101.json")
    assert second_default == Path("/tmp/open-omada-heartbeat-020000000102.json")
    assert default_heartbeat_path("02-00-00-00-01-01") == first_default

    first = tmp_path / first_default.name
    second = tmp_path / second_default.name
    write_heartbeat(
        first,
        phase="managed",
        mac=first_mac,
        controller_host="192.0.2.8",
        seq=1,
        now=lambda: 1000.0,
    )
    write_heartbeat(
        second,
        phase="managed",
        mac=second_mac,
        controller_host="192.0.2.8",
        seq=2,
        now=lambda: 1050.0,
    )

    assert json.loads(first.read_text(encoding="utf-8"))["seq"] == 1
    first_ok, _ = check_heartbeat(
        first, max_age_s=45.0, expected_mac=first_mac, now=lambda: 1015.0
    )
    second_ok, _ = check_heartbeat(
        second, max_age_s=45.0, expected_mac=second_mac, now=lambda: 1060.0
    )
    first_stale, stale_detail = check_heartbeat(
        first, max_age_s=45.0, expected_mac=first_mac, now=lambda: 1060.0
    )
    mismatch, mismatch_detail = check_heartbeat(
        first, max_age_s=45.0, expected_mac=second_mac, now=lambda: 1015.0
    )

    assert first_ok and second_ok
    assert not first_stale and "stale" in stale_detail
    assert not mismatch and "mismatch" in mismatch_detail


def test_cli_healthcheck_exit_codes(tmp_path):
    hb = tmp_path / "hb.json"
    mac = "02:00:00:00:00:01"
    env = _cli_environment()
    env["OMADA_HEARTBEAT_FILE"] = str(hb)
    env["OMADA_DEVICE_MAC"] = mac

    missing = _run_healthcheck(env, tmp_path)
    assert missing.returncode == 1

    write_heartbeat(
        hb,
        phase="managed",
        mac=mac,
        controller_host="192.0.2.8",
        seq=5,
    )
    healthy = _run_healthcheck(env, tmp_path)
    assert healthy.returncode == 0

    write_heartbeat(
        hb,
        phase="managed",
        mac="02:00:00:00:00:02",
        controller_host="192.0.2.8",
        seq=6,
    )
    mismatched = _run_healthcheck(env, tmp_path)
    assert mismatched.returncode == 1
    assert "MAC mismatch" in mismatched.stderr


def test_cli_healthcheck_uses_per_device_defaults(tmp_path):
    first_mac = "02:00:00:00:01:03"
    second_mac = "02:00:00:00:01:04"
    first = default_heartbeat_path(first_mac)
    second = default_heartbeat_path(second_mac)
    env = _cli_environment()
    env.pop("OMADA_HEARTBEAT_FILE", None)

    try:
        write_heartbeat(
            first,
            phase="managed",
            mac=first_mac,
            controller_host="192.0.2.8",
            seq=7,
        )
        write_heartbeat(
            second,
            phase="managed",
            mac=second_mac,
            controller_host="192.0.2.8",
            seq=8,
        )
        for mac in (first_mac, second_mac):
            env["OMADA_DEVICE_MAC"] = mac
            healthy = _run_healthcheck(env, tmp_path)
            assert healthy.returncode == 0, healthy.stderr
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
