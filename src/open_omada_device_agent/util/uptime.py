"""Format and parse TP-Link ECSP deviceInfo.upTime strings.

Omada Controller 6.3 (`com.tplink.smb.omada.common.util.aa.k`) tokenizes
`deviceInfo.upTime` with `StringTokenizer(s, " ")` followed by `":"`:
`<days> days <HH>:<MM>:<SS>`. Bare integer strings raise `NoSuchElementException`
on every inform and leave AP uptime blank on the controller.
"""
from __future__ import annotations


def format_ecsp_uptime(seconds: int | float) -> str:
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{days} days {hours:02d}:{minutes:02d}:{secs:02d}"


def parse_ecsp_uptime(value: str) -> int:
    parts = value.strip().split()
    if len(parts) != 3:
        raise ValueError(f"invalid ECSP upTime format: {value!r}")
    days = int(parts[0])
    hh, mm, ss = (int(piece.strip()) for piece in parts[2].split(":"))
    return days * 86400 + hh * 3600 + mm * 60 + ss
