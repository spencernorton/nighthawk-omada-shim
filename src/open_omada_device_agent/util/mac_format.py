from __future__ import annotations

from ..shared.domain import MacAddress


def to_omada(mac: str) -> str:
    """Convert a MAC address to Omada's dash-separated upper-case format."""
    return MacAddress(mac).omada


def unicast_mac(value: object) -> str | None:
    """Canonicalize a well-formed, non-placeholder physical MAC address."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    try:
        address = MacAddress(text).value
    except ValueError:
        return None
    compact = address.replace(":", "")
    dotted = ".".join(compact[i:i + 4] for i in (0, 4, 8))
    if text not in (address, address.replace(":", "-"), compact, dotted):
        return None
    if address == "00:00:00:00:00:00" or int(address[:2], 16) & 1:
        return None
    return address
