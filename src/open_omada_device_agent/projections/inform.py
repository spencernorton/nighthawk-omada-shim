"""Assemble domain observations into the ECSP inform read model."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from ..contexts.clients.domain import ClientPortalState, WirelessClientState
from ..util.uptime import format_ecsp_uptime

@dataclass(frozen=True)
class LanObservation:
    rate: float
    duplex: int
    port: str
    link_up: bool | None = None

class InformAssembler:
    def __init__(
        self,
        *,
        device_info: Callable[[], Mapping[str, Any]],
        lan: LanObservation | Callable[[], LanObservation],
        clients: Callable[[], tuple[WirelessClientState, ...]],
        client_projection: Callable[[tuple[WirelessClientState, ...]], list[dict[str, Any]]],
        wireless_projection: Callable[[], Mapping[str, Any]],
        uplink_traffic: Callable[[str, str], dict | None] | None = None,
    ) -> None:
        self._device_info = device_info
        self._lan = lan
        self._clients = clients
        self._client_projection = client_projection
        self._wireless_projection = wireless_projection
        self._uplink_traffic = uplink_traffic

    def build(self, *, need_reply: bool, uptime: int) -> dict[str, Any]:
        info = dict(self._device_info())
        info["isFactory"] = False
        info["upTime"] = _uptime_value(info.get("upTime"), fallback=uptime)
        lan = self._lan() if callable(self._lan) else self._lan
        body: dict[str, Any] = {
            "needReply": 1 if need_reply else 0,
            "deviceInfo": info,
            "lanInfo": {
                "rate": (
                    str(int(lan.rate))
                    if lan.rate.is_integer()
                    else str(lan.rate)
                ),
                "duplex": lan.duplex,
                "port": lan.port,
            },
        }
        if lan.rate > 0 or lan.link_up is False:
            body["uplinkPortStatus"] = [
                {
                    "port": lan.port,
                    "portType": 1,
                    "duplex": lan.duplex,
                    "link": int(lan.link_up is not False),
                    "speed": int(lan.rate),
                }
            ]
        if self._uplink_traffic is not None:
            traffic = self._uplink_traffic(lan.port, info["upTime"])
            if traffic is not None:
                body["lanTraffic"] = traffic
        clients = self._clients()
        if clients:
            projected_clients = self._client_projection(clients)
            body["clients"] = projected_clients
            portal_clients = [
                projected
                for client, projected in zip(clients, projected_clients, strict=False)
                if client.portal_state is not ClientPortalState.UNKNOWN
            ]
            if portal_clients:
                body["portalAuthClients"] = portal_clients
        body.update(self._wireless_projection())
        return body


def _uptime_value(value: Any, *, fallback: int) -> str:
    if value not in (None, ""):
        try:
            return format_ecsp_uptime(float(value))
        except (TypeError, ValueError):
            return str(value)
    return format_ecsp_uptime(fallback)
