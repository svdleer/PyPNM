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
    OIDs based on DOCS-PNM-MIB
    """
    
    # Bulk Data Transfer Configuration
    BULK_UPLOAD_CONTROL = "1.3.6.1.4.1.4491.2.1.27.1.1.1.4"
    BULK_DEST_PATH = "1.3.6.1.4.1.4491.2.1.27.1.1.1.3"
    BULK_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"
    
    # UTSC Configuration (correct OIDs from DOCS-PNM-MIB)
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
            
            # Convert IP address to hex bytes for SNMP
            ip_parts = tftp_ip.split(".")
            ip_hex = bytes([int(p) for p in ip_parts])
            
            await self.snmp.set(f"{self.BULK_CFG_BASE}.3{bulk_idx}", 1, Integer32)  # docsPnmBulkDataTransferCfgDestHostIpAddrType (1=ipv4)
            await self.snmp.set(f"{self.BULK_CFG_BASE}.4{bulk_idx}", ip_hex, OctetString)  # docsPnmBulkDataTransferCfgDestHostIpAddress (hex)
            await self.snmp.set(f"{self.BULK_CFG_BASE}.6{bulk_idx}", "./", OctetString)  # docsPnmBulkDataTransferCfgDestBaseUri
            await self.snmp.set(f"{self.BULK_CFG_BASE}.7{bulk_idx}", 1, Integer32)  # docsPnmBulkDataTransferCfgProtocol (1=TFTP)
            
            # 2. Enable auto upload (may not exist on all CMTS)
            try:
                await self.snmp.set(self.BULK_UPLOAD_CONTROL, 1, Integer32)  # docsPnmBulkUploadControl
            except Exception:
                pass  # OID may not exist on this CMTS model
            
            # 3. Configure UTSC parameters
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.3{idx}", trigger_mode, Integer32)
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.8{idx}", center_freq_hz, Unsigned32)
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.9{idx}", span_hz, Unsigned32)
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.10{idx}", num_bins, Unsigned32)
            await self.snmp.set(f"{self.UTSC_CFG_BASE}.13{idx}", filename, OctetString)
            
            # 4. CM MAC for trigger mode 6
            if trigger_mode == 6 and cm_mac:
                await self.snmp.set(f"{self.UTSC_CFG_BASE}.6{idx}", cm_mac, OctetString)  # docsPnmCmtsUtscCfgCmMacAddr
                if logical_ch_ifindex:
                    await self.snmp.set(f"{self.UTSC_CFG_BASE}.2{idx}", logical_ch_ifindex, Integer32)
            
            return {"success": True, "cmts_ip": str(self.cmts_ip)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def start(self) -> dict:
        try:
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            oid = f"{self.UTSC_CTRL_BASE}.1{idx}"  # docsPnmCmtsUtscCtrlInitiateTest
            await self.snmp.set(oid, 1, Integer32)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
