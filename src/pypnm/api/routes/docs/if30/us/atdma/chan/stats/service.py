# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from pypnm.api.routes.common.classes.common_endpoint_classes.schema.base_connect_request import (
    SNMPConfig,
)
from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import (
    BandwidthHz,
    ChannelId,
    InetAddressStr,
    MacAddressStr,
    PowerdB,
    PowerdBmV,
)
from pypnm.pnm.analysis.us_drw import (
    DwrChannelPowerModel,
    DwrDynamicWindowRangeChecker,
    DwrWindowCheckModel,
)
from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData


class UsScQamChannelService:
    """
    Service for retrieving DOCSIS Upstream SC-QAM channel information and
    pre-equalization data from a cable modem using SNMP.

    Attributes:
        cm (CableModem): An instance of the CableModem class used to perform SNMP operations.
    """

    DEFAULT_DWR_WARNING_DB: PowerdB = PowerdB(6.0)
    DEFAULT_DWR_VIOLATION_DB: PowerdB = PowerdB(12.0)

    def __init__(self, mac_address: MacAddressStr,
                 ip_address: InetAddressStr,
                 snmp_config: SNMPConfig) -> None:
        """
        Initializes the service with a MAC and IP address.

        Args:
            mac_address (str): MAC address of the target cable modem.
            ip_address (str): IP address of the target cable modem.
        """
        self.cm = CableModem(mac_address=MacAddress(mac_address),
                             inet=Inet(ip_address),
                             write_community=snmp_config.snmp_v2c.community)

    async def get_upstream_entries(
        self,
        dwr_warning_db: PowerdB = DEFAULT_DWR_WARNING_DB,
        dwr_violation_db: PowerdB = DEFAULT_DWR_VIOLATION_DB,
    ) -> dict[str, object]:
        """
        Fetches DOCSIS Upstream SC-QAM channel entries.

        Returns:
            Dict[str, object]: Upstream channel entries with optional DWR evaluation summary.
        """
        entries = await self.cm.getDocsIfUpstreamChannelEntry()
        entry_dicts = [entry.model_dump() for entry in entries]

        channel_powers: list[DwrChannelPowerModel] = []
        for entry in entries:
            tx_power = entry.entry.docsIf3CmStatusUsTxPower
            if tx_power is None:
                continue
            channel_powers.append(
                DwrChannelPowerModel(
                    channel_id=ChannelId(entry.channel_id),
                    tx_power_dbmv=PowerdBmV(tx_power),
                )
            )

        dwr_check: DwrWindowCheckModel | None = None
        if len(channel_powers) >= DwrDynamicWindowRangeChecker.MIN_CHANNELS:
            try:
                checker = DwrDynamicWindowRangeChecker(
                    dwr_violation_db=dwr_violation_db,
                    dwr_warning_db=dwr_warning_db,
                )
                dwr_check = checker.evaluate(channel_powers)
            except Exception:
                dwr_check = None

        return {
            "entries": entry_dicts,
            "dwr_window_check": (dwr_check.model_dump() if dwr_check is not None else None),
        }

    async def get_upstream_pre_equalizations(self) ->  dict[int, dict]:
        """
        Fetches upstream pre-equalization coefficient data.

        Returns:
            List[dict]: A dictionary containing per-channel equalizer data with real, imag,
                        magnitude, and power (dB) for each tap.
        """
        entries_payload = await self.get_upstream_entries()
        channel_widths: dict[int, BandwidthHz] = {}
        for entry in entries_payload.get("entries", []):
            index = entry.get("index")
            entry_data = entry.get("entry") or {}
            channel_width = entry_data.get("docsIfUpChannelWidth")
            if isinstance(index, int) and isinstance(channel_width, int) and channel_width > 0:
                channel_widths[index] = BandwidthHz(channel_width)

        pre_eq_data: DocsEqualizerData = await self.cm.getDocsIf3CmStatusUsEqData(
            channel_widths=channel_widths
        )
        return pre_eq_data.to_dict()
