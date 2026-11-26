import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rs700_beacon_observer.py"
BSSID = "02:01:02:03:04:05"
SECOND = "02:01:02:03:04:09"


@pytest.fixture()
def collect(tmp_path):
    cli = tmp_path / "wpa_cli"
    cli.write_text(
        "#!/bin/sh\n"
        'test "$1" = "-i" && test "$2" = "wlan0" && test "$3" = "bss" || exit 2\n'
        'test -e "$CACHE/denied" && exit 1\n'
        'cat "$CACHE/$4" 2>/dev/null || echo FAIL\n'
    )
    cli.chmod(0o700)

    def run(*bssids):
        command = [sys.executable, str(SCRIPT), "--interface", "wlan0"]
        for mac in bssids:
            command.extend(["--bssid", mac])
        return subprocess.run(
            command, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CACHE": str(tmp_path)},
        )

    return run


def test_allowlist_age_zero_load_and_missing_load(collect, tmp_path):
    (tmp_path / BSSID).write_text(
        f"bssid={BSSID}\nage=137\nfreq=6295\nssid=\n"
        "ie=0001610b050100000000\nbeacon_ie=0b050300ff0000\n"
    )
    (tmp_path / SECOND).write_text(f"bssid={SECOND}\nage=14\nfreq=2412\nie=0000\n")
    start = int(time.time())
    run = collect(BSSID.upper(), SECOND, "00:01:02:03:04:05")
    finish = int(time.time())
    assert run.returncode == 0
    doc = json.loads(run.stdout)
    assert doc["version"] == 1
    assert doc["radios"].keys() == {BSSID, SECOND}
    first = doc["radios"][BSSID]
    assert first["frequency_mhz"] == 6295
    assert start - 137 <= first["observed_at"] <= finish - 137
    assert first["utilization_255"] == 0
    assert "utilization_255" not in doc["radios"][SECOND]


@pytest.mark.parametrize("response", [
    "bssid=02:01:02:03:04:09\nage=0\nfreq=6295",
    f"bssid={BSSID}\nage=-1\nfreq=6295",
    f"bssid={BSSID}\nfreq=6295",
    f"bssid={BSSID}\nage=0\nfreq=0",
])
def test_cache_entry_requires_matching_bssid_age_and_frequency(collect, tmp_path, response):
    (tmp_path / BSSID).write_text(response)
    run = collect(BSSID)
    assert run.returncode == 0
    assert json.loads(run.stdout)["radios"] == {}


@pytest.mark.parametrize(("probe", "beacon", "expected"), [
    ("0000", "0b050500d30000", 211),
    ("0b05aabb", "001", None),
    ("0b0401020304", "", None),
    ("0b0501002000000b050100210000", "", None),
])
def test_missing_or_malformed_load(collect, tmp_path, probe, beacon, expected):
    (tmp_path / BSSID).write_text(
        f"bssid={BSSID}\nage=0\nfreq=5200\nie={probe}\nbeacon_ie={beacon}\n"
    )
    run = collect(BSSID)
    assert run.returncode == 0
    assert json.loads(run.stdout)["radios"][BSSID].get("utilization_255") == expected


def test_failed_control_socket_read_emits_no_snapshot(collect, tmp_path):
    (tmp_path / "denied").touch()
    run = collect(BSSID)
    assert run.returncode != 0
    assert not run.stdout


def test_rejects_non_bssid_before_invoking_supplicant(collect):
    assert collect("FIRST").returncode == 2
