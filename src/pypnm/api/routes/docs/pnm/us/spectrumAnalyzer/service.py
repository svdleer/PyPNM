# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration
# Based on DOCSIS UTSC (Upstream Triggered Spectrum Capture)

from __future__ import annotations

import logging

from pypnm.lib.inet import Inet
from pypnm.snmp.snmp_v2c import Snmp_v2c


class CmtsUtscService:
    """CMTS-Based Upstream Triggered Spectrum Capture (UTSC) Service
    
    UTSC is CMTS-based, not modem-based. SNMP commands go to CMTS using RF port ifIndex.
    """
    
    UTSC_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.1.1"
    UTSC_CTRL_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.2.1"
    
    def __init__(self, cmts_ip: Inet, rf_port_ifindex: int, community: str = "private") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cmts_ip = cmts_ip
        self.rf_port_ifindex = rf_port_ifindex
        self.snmp = Snmp_v2c(inet=cmts_ip, read_community=community, write_community=community)
        self.cfg_idx = 1
    
    async def configure(
        self, 
        center_freq_hz: int, 
        span_hz: int, 
        num_bins: int, 
        trigger_mode: int, 
        filename: str,
        cm_mac: str | None = None,
        logical_ch_ifindex: int | None = None
    ) -> dict:
        try:
            base = self.UTSC_CFG_BASE
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            
            await self.snmp.set_int(f"{base}.3{idx}", trigger_mode)
            await self.snmp.set_uint(f"{base}.8{idx}", center_freq_hz)
            await self.snmp.set_uint(f"{base}.9{idx}", span_hz)
            await self.snmp.set_uint(f"{base}.10{idx}", num_bins)
            await self.snmp.set_int(f"{base}.17{idx}", 2)
            await self.snmp.set_octet_string(f"{base}.13{idx}", filename)
            
            # CM MAC trigger mode (6) requires MAC address
            if trigger_mode == 6 and cm_mac:
                await self.snmp.set_mac_address(f"{base}.6{idx}", cm_mac)
                if logical_ch_ifindex:
                    await self.snmp.set_int(f"{base}.2{idx}", logical_ch_ifindex)
            
            return {"success": True, "cmts_ip": str(self.cmts_ip)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def start(self) -> dict:
        try:
            oid = f"{self.UTSC_CTRL_BASE}.1.{self.rf_port_ifindex}.{self.cfg_idx}"
            await self.snmp.set_int(oid, 1)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
