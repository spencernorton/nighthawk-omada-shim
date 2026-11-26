"""Reference access-point profile backed by generic Linux observations."""
from collections.abc import Callable
from typing import Any

from ....application.contracts import PlatformCapabilities
from ....application.settings import AgentSettings
from ....capabilities import ap_components_v2
from ....contexts.device.domain import DeviceIdentity
from ....contexts.wireless.domain import RadioBand
from ....shared.domain import MacAddress
from ....system_tools import get_cpu_utilization, get_memory_utilization, get_system_uptime
from ....util.uptime import format_ecsp_uptime


RADIO_ID_BY_BAND: dict[RadioBand, int] = {
    RadioBand.TWO_G: 0,
    RadioBand.FIVE_G: 1,
    RadioBand.FIVE_G2: 2,
    RadioBand.SIX_G: 3,
}

BAND_LABEL_BY_BAND: dict[RadioBand, str] = {
    RadioBand.TWO_G: "2.4G",
    RadioBand.FIVE_G: "5G",
    RadioBand.FIVE_G2: "5G2",
    RadioBand.SIX_G: "6G",
}

# Omada stores channel width support as regulatory-domain bit flags. These
# values are the same constants used by Controller 6.2.14.11's channel code.
WIDTH_FLAG_2G_HT40 = 0x20000 | 0x40000
WIDTH_FLAG_5G_HT40_VHT80 = 0x20000 | 0x40000 | 0x800100
WIDTH_FLAG_6G_20_40_80_160 = 0x100 | 0x20000 | 0x40000 | 0x800000 | 0x1000000

CHANNELS_BY_BAND: dict[RadioBand, tuple[tuple[int, int, int, int], ...]] = {
    RadioBand.TWO_G: tuple(
        (channel, 2407 + channel * 5, 20, WIDTH_FLAG_2G_HT40)
        for channel in range(1, 14)
    ),
    RadioBand.FIVE_G: (
        (36, 5180, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (40, 5200, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (44, 5220, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (48, 5240, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (149, 5745, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (153, 5765, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (157, 5785, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (161, 5805, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (165, 5825, 23, WIDTH_FLAG_5G_HT40_VHT80),
    ),
    RadioBand.FIVE_G2: (
        (149, 5745, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (153, 5765, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (157, 5785, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (161, 5805, 23, WIDTH_FLAG_5G_HT40_VHT80),
        (165, 5825, 23, WIDTH_FLAG_5G_HT40_VHT80),
    ),
    RadioBand.SIX_G: (
        (5, 5975, 23, WIDTH_FLAG_6G_20_40_80_160),
        (21, 6055, 23, WIDTH_FLAG_6G_20_40_80_160),
        (37, 6135, 23, WIDTH_FLAG_6G_20_40_80_160),
        (53, 6215, 23, WIDTH_FLAG_6G_20_40_80_160),
        (69, 6295, 23, WIDTH_FLAG_6G_20_40_80_160),
    ),
}


# Controller 6.3.0.111 tri-band templates (initDeviceModelTemplateData)
# supply the radio descriptors Omada needs for EAP770/EAP773 adoption. Feature
# switches stay conservative: supportSsidNum follows the southbound, and mesh,
# MLO, roaming, DFS and cluster support are not inherited from the template
# because the southbound cannot apply or observe those behaviors.
TRI_BAND_MODELS = {"EAP770", "EAP773"}

TRI_BAND_RADIO_CAP: dict[int, dict[str, Any]] = {
    0: {"minPow": 4, "maxPow": 25, "limitMaxPow": 60, "mimo": 2, "ofdma": 1,
        "mcsLevel": 13, "ofdmaEnable": 0, "supportMlo": False,
        "supportMaxAssocClient": 128},
    1: {"minPow": 4, "maxPow": 25, "limitMaxPow": 60, "mimo": 2, "ofdma": 1,
        "mcsLevel": 13, "ofdmaEnable": 0, "supportMlo": False,
        "supportMaxAssocClient": 128},
    3: {"minPow": 4, "maxPow": 23, "limitMaxPow": 60, "mimo": 2, "ofdma": 1,
        "mcsLevel": 13, "ofdmaEnable": 0, "supportMlo": False,
        "supportMaxAssocClient": 128},
}

TRI_BAND_DEVICE_MISC: dict[str, Any] = {
    "support_5g": True,
    "support_11ac": True,
    "support_lag": False,
    "supportMesh": 0,
    "maxTxPower": 0,
    "minPower2G": 4,
    "maxPower2G": 25,
    "minPower5G": 4,
    "maxPower5G": 25,
    "uplinkPort": "LAN Port",
    "supportRoaming": 0,
    "supportDfs": 0,
    "supportCluster": 0,
    "category": "EAP",
    "modelType": "NORMAL",
}


class GenericOpenWrtAccessPointProfile:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        ip_address: Callable[[], str],
        capabilities: PlatformCapabilities,
        uptime_seconds: Callable[[], int | float | None] | None = None,
        memory_utilization: Callable[[], int | float | None] | None = None,
        include_host_metrics: bool = True,
    ) -> None:
        self._settings = settings
        self._ip_address = ip_address
        self._capabilities = capabilities
        self._uptime_seconds = uptime_seconds
        self._memory_utilization = memory_utilization
        self._include_host_metrics = include_host_metrics

    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(
            mac=MacAddress(self._settings.mac),
            name=self._settings.device_name,
            model=self._settings.model,
            model_version=self._settings.model_version,
            hardware_version=self._settings.hardware_version,
            firmware_version=self._settings.firmware_version,
        )

    def device_info(self) -> dict[str, Any]:
        identity = self.identity()
        info = {
            "ip": self._ip_address(),
            "isFactory": True,
            "name": identity.name,
            "model": identity.model,
            "modelVersion": identity.model_version,
            "firmwareVersion": identity.firmware_version,
            "hardwareVersion": identity.hardware_version,
            "upTime": format_ecsp_uptime(
                get_system_uptime()
                if self._uptime_seconds is None or (reported := self._uptime_seconds()) is None
                else reported
            ),
            "wirelessLinked": False,
            "p2p": False,
            "supportBridge": 0,
            "mainMac": identity.mac.omada,
        }
        if self._include_host_metrics:
            info["cpuUti"] = get_cpu_utilization()
        if self._memory_utilization is not None:
            reported_memory = self._memory_utilization()
            if reported_memory is not None:
                info["memUti"] = reported_memory
        elif self._include_host_metrics:
            info["memUti"] = get_memory_utilization()
        return info

    def device_misc(self) -> dict[str, Any]:
        if self._settings.model in TRI_BAND_MODELS:
            misc = dict(TRI_BAND_DEVICE_MISC)
            misc["customizeRegion"] = self._settings.customize_region
            return misc
        return {
            "modelType": "NORMAL",
            "support_11ac": False,
            "support_lag": False,
            "supportMesh": 0,
            "customizeRegion": self._settings.customize_region,
            "support_channelLimit": False,
            "channelLimit_mode": 0,
            "supportDfs": 0,
            "lanPortsNum": 1,
            "lanVlanPorts": [],
            "lanPoePorts": [],
            "supportRoaming": 0,
        }

    def components_v2(self) -> dict[str, str]:
        return ap_components_v2(self._capabilities)

    def channel_info(self) -> tuple[dict[str, Any], ...]:
        if not self._capabilities.supports_wlan_config:
            return ()
        return tuple(
            {
                "radioId": RADIO_ID_BY_BAND[band],
                "band": BAND_LABEL_BY_BAND[band],
                "channelList": [
                    _channel_detail(channel, freq, max_power, width_flag)
                    for channel, freq, max_power, width_flag in CHANNELS_BY_BAND[band]
                ],
            }
            for band in self._capabilities.radio_bands
            if band in CHANNELS_BY_BAND
        )

    def radio_cap(self) -> tuple[dict[str, Any], ...]:
        if not self._capabilities.supports_wlan_config:
            return ()
        max_ssids = max(1, self._capabilities.max_ssids)
        if self._settings.model in TRI_BAND_MODELS:
            return tuple(
                {"radioId": RADIO_ID_BY_BAND[band],
                 **TRI_BAND_RADIO_CAP[RADIO_ID_BY_BAND[band]],
                 "supportSsidNum": max_ssids}
                for band in self._capabilities.radio_bands
                if RADIO_ID_BY_BAND.get(band) in TRI_BAND_RADIO_CAP
            )
        return tuple(
            _radio_cap_item(RADIO_ID_BY_BAND[band], max_ssids=max_ssids)
            for band in self._capabilities.radio_bands
            if band in RADIO_ID_BY_BAND
        )


def _radio_cap_item(radio_id: int, *, max_ssids: int) -> dict[str, Any]:
    return {
        "radioId": radio_id,
        "minPow": 1,
        "maxPow": 20,
        "maxPowOd": 20,
        "limitMaxPow": 20,
        "mimo": 1,
        "ofdma": 0,
        "ofdmaEnable": 0,
        "mcsLevel": 7,
        "supportSsidNum": max_ssids,
        "supportAntennaDirection": [],
        "supportMaxClient": 64,
        "supportMlo": False,
        "supportMaxAssocClient": 64,
        "supportAnteGainSetting": 0,
        "supportCSA": 0,
        "supportCSAWidth": 0,
        "supportMgtSsid": 0,
    }


def _channel_detail(
    channel: int,
    freq: int,
    max_power: int,
    width_flag: int,
) -> dict[str, int]:
    return {
        "fr": freq,
        "vl": channel,
        "mPow": max_power,
        "cFlag": width_flag,
        "dFlag": 0,
        "lm": 1,
        "mPowOd": 0,
        "cFlagOd": 0,
    }
