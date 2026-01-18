# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration
# Based on DOCSIS UTSC (Upstream Triggered Spectrum Capture)

from __future__ import annotations

import logging

from pysnmp.proto.rfc1902 import Integer32, OctetString, Unsigned32
from pypnm.lib.inet import Inet
from pypnm.snmp.snmp_v2c import Snmp_v2c


class CmtsUtscService:
    """CMTS-Based Upstream Triggered Spectrum Capture (UTSC) Service
    
    UTSC is CMTS-based, not modem-based. SNMP commands go to CMTS using RF port ifIndex.
    """
    
    # Bulk Data Transfer Configuration
    BULK_UPLOAD_CONTROL = "1.3.6.1.4.1.4491.2.1.27.1.1.1.4"
    BULK_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"
    
    # UTSC Configuration  
    UTSC_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
    UTSC_CTRL_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1"
    UTSC_STATUS_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1"
    
    def __init__(self, cmts_ip: Inet, rf_port_ifindex: int, community: str = "private") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cmts_ip = cmts_ip
        self.rf_port_ifindex = rf_port_ifindex
        self.snmp = Snmp_v2c(cmts_ip, read_community=community, write_community=community)
        self.cfg_idx = 1
    
    async def configure(
        self, 
        center_freq_hz: int, 
        span_hz: int, 
        num_bins: int, 
        trigger_mode: int, 
        filename: str,
        tftp_ip: str,
        cm_mac: str | None = None,
        logical_ch_ifindex: int | None = None
    ) -> dict:
        try:
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            
            # 1. Configure Bulk Data Transfer (TFTP)
            bulk_idx = f".{self.cfg_idx}"
            await self.snmp.set(f"{self.BULK_CFG_BASE}.3{bulk_idx}", 1, Integer32)  # IP type = IPv4
            await self.snmp.set(f"{self.BULK_CFG_BASE}.4{bulk_idx}", tftp_ip, OctetString)  # TFTP IP
            await self.snmp.set(f"{self.BULK_CFG_BASE}.6{bulk_idx}", "/pnm/utsc", OctetString)  # Base URI
            await self.snmp.set(f"{self.BULK_CFG_BASE}.7{bulk_idx}", 1, Integer32)  # Protocol = TFTP
            
            # 2. Enable auto upload
            await self.snmp.set(self.BULK_UPLOAD_CONTROL, 1, Integer32)
            
            # 3. Configure UTSC
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.3{idx}", trigger_mode, Integer32)  # Trigger mode
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.8{idx}", center_freq_hz, Unsigned32)  # Center freq
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.9{idx}", span_hz, Unsigned32)  # Span
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.10{idx}", num_bins, Unsigned32)  # Num bins
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.13{idx}", filename, OctetString)  # Filename
            
            # 4. CM MAC for trigger mode 6
            if trigger_mode == 6 and cm_mac:
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            oid = f"{self.UTSC_CTRL_BASE}.1{ctetString)
                if logical_ch_ifindex:
                    await self.snmp.set(f"{self.UTSC_CFG_BASE}.2{idx}", logical_ch_ifindex, Integer32)
            
            return {"success": True, "cmts_ip": str(self.cmts_ip)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def start(self) -> dict:
        try:
            oid = f"{self.UTSC_CTRL_BASE}.1.{self.rf_port_ifindex}.{self.cfg_idx}"
            await self.snmp.set(oid, 1, Integer32)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
