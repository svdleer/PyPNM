# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Service for CMTS Upstream OFDMA RxMER operations.

This module provides async methods for CMTS-side US OFDMA RxMER
measurements using pysnmp for direct CMTS SNMP communication.

OIDs used (from DOCS-PNM-MIB):
- docsIf3CmtsCmRegStatusMacAddr: 1.3.6.1.4.1.4491.2.1.20.1.3.1.2
- docsIf31CmtsCmUsOfdmaChannelStatus: 1.3.6.1.4.1.4491.2.1.28.1.5.1.1  
- docsPnmCmtsUsOfdmaRxMerTable: 1.3.6.1.4.1.4491.2.1.27.1.3.8
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any, Optional

from pysnmp.proto.rfc1902 import Gauge32, Integer32, OctetString

from pypnm.snmp.snmp_v2c import Snmp_v2c
from pypnm.lib.inet import Inet


logger = logging.getLogger(__name__)


class MeasStatus(IntEnum):
    """Measurement Status (docsPnmCmtsUsOfdmaRxMerMeasStatus)"""
    OTHER = 1
    INACTIVE = 2
    BUSY = 3
    SAMPLE_READY = 4
    ERROR = 5
    RESOURCE_UNAVAILABLE = 6


class CmtsUsOfdmaRxMerService:
    """
    Service for CMTS Upstream OFDMA RxMER operations.
    
    Provides async methods for:
    - Discovering modem's OFDMA channel ifIndex
    - Starting/monitoring US OFDMA RxMER measurements
    """
    
    # OID definitions
    OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
    OID_CM_REG_MAC = "1.3.6.1.4.1.4491.2.1.20.1.3.1.2"  # docsIf3CmtsCmRegStatusMacAddr
    OID_CM_OFDMA_STATUS = "1.3.6.1.4.1.4491.2.1.28.1.5.1.1"  # docsIf31CmtsCmUsOfdmaChannelStatusTable
    
    # US OFDMA RxMER Table (docsPnmCmtsUsOfdmaRxMerTable)
    # Correct OID base: 1.3.6.1.4.1.4491.2.1.27.1.3.7.1
    OID_US_RXMER_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.3.7.1"
    OID_US_RXMER_ENABLE = f"{OID_US_RXMER_TABLE}.1"      # docsPnmCmtsUsOfdmaRxMerEnable
    OID_US_RXMER_CM_MAC = f"{OID_US_RXMER_TABLE}.2"      # docsPnmCmtsUsOfdmaRxMerCmMac
    OID_US_RXMER_PRE_EQ = f"{OID_US_RXMER_TABLE}.3"      # docsPnmCmtsUsOfdmaRxMerPreEq
    OID_US_RXMER_NUM_AVGS = f"{OID_US_RXMER_TABLE}.4"    # docsPnmCmtsUsOfdmaRxMerNumAvgs
    OID_US_RXMER_MEAS_STATUS = f"{OID_US_RXMER_TABLE}.5" # docsPnmCmtsUsOfdmaRxMerMeasStatus
    OID_US_RXMER_FILENAME = f"{OID_US_RXMER_TABLE}.6"    # docsPnmCmtsUsOfdmaRxMerFileName
    OID_US_RXMER_DEST_INDEX = f"{OID_US_RXMER_TABLE}.7"  # docsPnmCmtsUsOfdmaRxMerDestinationIndex
    
    # Bulk Data Transfer Config Table (docsPnmBulkDataTransferCfgTable)
    OID_BULK_CFG_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"
    OID_BULK_CFG_HOSTNAME = f"{OID_BULK_CFG_TABLE}.2"    # DestHostname
    OID_BULK_CFG_IP_TYPE = f"{OID_BULK_CFG_TABLE}.3"     # DestHostIpAddrType
    OID_BULK_CFG_IP_ADDR = f"{OID_BULK_CFG_TABLE}.4"     # DestHostIpAddress
    OID_BULK_CFG_PORT = f"{OID_BULK_CFG_TABLE}.5"        # DestPort
    OID_BULK_CFG_BASE_URI = f"{OID_BULK_CFG_TABLE}.6"    # DestBaseUri
    OID_BULK_CFG_PROTOCOL = f"{OID_BULK_CFG_TABLE}.7"    # Protocol (1=tftp)
    OID_BULK_CFG_LOCAL_STORE = f"{OID_BULK_CFG_TABLE}.8" # LocalStore
    OID_BULK_CFG_ROW_STATUS = f"{OID_BULK_CFG_TABLE}.9"  # RowStatus
    
    def __init__(
        self,
        cmts_ip: str,
        community: str = "private",
        write_community: Optional[str] = None
    ):
        """
        Initialize CMTS US OFDMA RxMER service.
        
        Args:
            cmts_ip: CMTS IP address
            community: SNMP read community
            write_community: SNMP write community (defaults to community)
        """
        self.cmts_ip = cmts_ip
        self.community = community
        self.write_community = write_community or community
        self._snmp: Optional[Snmp_v2c] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def _get_snmp(self) -> Snmp_v2c:
        """Get or create SNMP client instance."""
        if self._snmp is None:
            self._snmp = Snmp_v2c(
                Inet(self.cmts_ip),
                read_community=self.community,
                write_community=self.write_community,
                timeout=10,
                retries=2
            )
        return self._snmp
    
    def close(self):
        """Close SNMP connection."""
        if self._snmp:
            self._snmp.close()
            self._snmp = None
    
    @staticmethod
    def mac_to_hex_octets(mac_address: str) -> str:
        """Convert MAC address to hex octets string for SNMP SET."""
        mac = mac_address.lower().replace(":", "").replace("-", "").replace(".", "")
        return bytes.fromhex(mac).decode('latin-1')
    
    @staticmethod
    def normalize_mac(mac_address: str) -> str:
        """Normalize MAC address to lowercase colon-separated format."""
        mac = mac_address.lower().replace("-", ":").replace(".", "")
        if ":" not in mac:
            mac = ":".join([mac[i:i+2] for i in range(0, 12, 2)])
        return mac
    
    async def discover_cm_index(self, cm_mac: str) -> Optional[int]:
        """
        Find CM index on CMTS from MAC address.
        
        Args:
            cm_mac: Cable modem MAC address
            
        Returns:
            CM index (docsIf3CmtsCmRegStatusIndex) or None
        """
        snmp = self._get_snmp()
        mac_normalized = self.normalize_mac(cm_mac)
        
        self.logger.info(f"Looking for CM MAC {mac_normalized} on CMTS {self.cmts_ip}")
        
        try:
            results = await snmp.bulk_walk(self.OID_CM_REG_MAC, max_repetitions=50)
            
            if not results:
                self.logger.warning("No CM registration entries found")
                return None
            
            for var_bind in results:
                oid_str = str(var_bind[0])
                value = var_bind[1]
                
                # Convert SNMP OctetString to MAC format
                if hasattr(value, 'prettyPrint'):
                    mac_hex = value.prettyPrint()
                    # Handle "0x001122334455" format
                    if mac_hex.startswith("0x"):
                        mac_hex = mac_hex[2:]
                    # Convert to colon format
                    if len(mac_hex) == 12:
                        found_mac = ":".join([mac_hex[i:i+2].lower() for i in range(0, 12, 2)])
                        if found_mac == mac_normalized:
                            # Extract CM index from OID suffix
                            cm_index = int(oid_str.split(".")[-1])
                            self.logger.info(f"Found CM index: {cm_index}")
                            return cm_index
            
            self.logger.warning(f"CM MAC {mac_normalized} not found on CMTS")
            return None
            
        except Exception as e:
            self.logger.error(f"Error discovering CM index: {e}")
            return None
    
    async def discover_ofdma_ifindex(self, cm_index: int) -> Optional[int]:
        """
        Find OFDMA channel ifIndex for a cable modem.
        
        Args:
            cm_index: CM registration index
            
        Returns:
            OFDMA channel ifIndex or None
        """
        snmp = self._get_snmp()
        
        self.logger.info(f"Looking for OFDMA channel for CM index {cm_index}")
        
        try:
            results = await snmp.bulk_walk(self.OID_CM_OFDMA_STATUS, max_repetitions=50)
            
            if not results:
                self.logger.warning("No OFDMA status entries found")
                return None
            
            for var_bind in results:
                oid_str = str(var_bind[0])
                
                # OID format: .1.3.6.1.4.1.4491.2.1.28.1.5.1.1.<cmIndex>.<ofdmaIfIndex>
                if f".{cm_index}." in oid_str:
                    parts = oid_str.split(".")
                    for i, part in enumerate(parts):
                        if part == str(cm_index) and i + 1 < len(parts):
                            ofdma_ifindex = int(parts[i + 1])
                            # OFDMA ifindexes are typically in the 843087xxx range
                            if ofdma_ifindex >= 843087000:
                                self.logger.info(f"Found OFDMA ifIndex: {ofdma_ifindex}")
                                return ofdma_ifindex
            
            self.logger.warning(f"No OFDMA channel found for CM index {cm_index}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error discovering OFDMA ifIndex: {e}")
            return None
    
    async def discover_modem_ofdma(self, cm_mac: str) -> dict[str, Any]:
        """
        Discover modem's OFDMA channel information.
        
        Args:
            cm_mac: Cable modem MAC address
            
        Returns:
            Dict with cm_index, ofdma_ifindex, and success status
        """
        cm_index = await self.discover_cm_index(cm_mac)
        if not cm_index:
            return {"success": False, "error": "CM not found on CMTS", "cm_mac_address": cm_mac}
        
        ofdma_ifindex = await self.discover_ofdma_ifindex(cm_index)
        if not ofdma_ifindex:
            return {
                "success": False,
                "error": "No OFDMA channel for this modem",
                "cm_mac_address": cm_mac,
                "cm_index": cm_index
            }
        
        # Get OFDMA channel description
        snmp = self._get_snmp()
        description = None
        try:
            result = await snmp.get(f"{self.OID_IF_DESCR}.{ofdma_ifindex}")
            if result:
                description = str(result[0][1])
        except Exception:
            pass
        
        return {
            "success": True,
            "cm_mac_address": cm_mac,
            "cm_index": cm_index,
            "ofdma_ifindex": ofdma_ifindex,
            "ofdma_description": description
        }
    
    async def start_measurement(
        self,
        ofdma_ifindex: int,
        cm_mac: str,
        filename: str = "us_rxmer",
        pre_eq: bool = True,
        num_averages: int = 1,
        destination_index: int = 0
    ) -> dict[str, Any]:
        """
        Start Upstream OFDMA RxMER measurement.
        
        Args:
            ofdma_ifindex: OFDMA channel ifIndex
            cm_mac: Cable modem MAC address
            filename: Output filename
            pre_eq: Enable pre-equalization
            num_averages: Number of averages
            destination_index: Bulk transfer destination index (0=local only, 
                             >0=use docsPnmBulkDataTransferCfgTable row)
            
        Returns:
            Dict with success status and details
        """
        snmp = self._get_snmp()
        idx = f".{ofdma_ifindex}"
        
        self.logger.info(f"Starting US RxMER for OFDMA ifIndex {ofdma_ifindex}, CM MAC {cm_mac}, dest={destination_index}")
        
        try:
            # 1. Set filename
            await snmp.set(
                f"{self.OID_US_RXMER_FILENAME}{idx}",
                filename,
                OctetString
            )
            
            # 2. Set CM MAC address
            mac_octets = self.mac_to_hex_octets(cm_mac)
            await snmp.set(
                f"{self.OID_US_RXMER_CM_MAC}{idx}",
                mac_octets,
                OctetString
            )
            
            # 3. Set pre-equalization (1=true, 2=false)
            pre_eq_val = 1 if pre_eq else 2
            await snmp.set(
                f"{self.OID_US_RXMER_PRE_EQ}{idx}",
                pre_eq_val,
                Integer32
            )
            
            # 4. Set number of averages (Gauge32)
            await snmp.set(
                f"{self.OID_US_RXMER_NUM_AVGS}{idx}",
                num_averages,
                Gauge32
            )
            
            # 5. Set destination index for bulk upload (0=local storage only, Gauge32)
            if destination_index > 0:
                await snmp.set(
                    f"{self.OID_US_RXMER_DEST_INDEX}{idx}",
                    destination_index,
                    Gauge32
                )
            
            # 6. Enable measurement (1=true)
            await snmp.set(
                f"{self.OID_US_RXMER_ENABLE}{idx}",
                1,
                Integer32
            )
            
            return {
                "success": True,
                "message": "US OFDMA RxMER measurement started",
                "ofdma_ifindex": ofdma_ifindex,
                "cm_mac_address": cm_mac,
                "filename": filename,
                "destination_index": destination_index
            }
            
        except Exception as e:
            self.logger.error(f"Failed to start US RxMER: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_status(self, ofdma_ifindex: int) -> dict[str, Any]:
        """
        Get US OFDMA RxMER measurement status.
        
        Args:
            ofdma_ifindex: OFDMA channel ifIndex
            
        Returns:
            Dict with measurement status
        """
        snmp = self._get_snmp()
        
        try:
            result = await snmp.get(f"{self.OID_US_RXMER_MEAS_STATUS}.{ofdma_ifindex}")
            
            if not result:
                return {"success": False, "error": "No response from CMTS"}
            
            status_value = int(result[0][1])
            status_name = MeasStatus(status_value).name if status_value in [e.value for e in MeasStatus] else "unknown"
            
            status = {
                "success": True,
                "ofdma_ifindex": ofdma_ifindex,
                "meas_status": status_value,
                "meas_status_name": status_name,
                "is_ready": status_value == MeasStatus.SAMPLE_READY,
                "is_busy": status_value == MeasStatus.BUSY,
                "is_error": status_value == MeasStatus.ERROR
            }
            
            # Get filename from configuration table (with timestamp)
            try:
                filename_result = await snmp.get(f"{self.OID_US_RXMER_FILENAME}.{ofdma_ifindex}")
                if filename_result:
                    status["filename"] = str(filename_result[0][1])
            except Exception:
                pass
            
            return status
            
        except Exception as e:
            self.logger.error(f"Failed to get US RxMER status: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_bulk_destinations(self) -> dict[str, Any]:
        """
        Get list of configured bulk data transfer destinations.
        
        These destinations can be used with destination_index parameter
        in start_measurement() to upload results via TFTP.
        
        Returns:
            Dict with list of configured destinations
        """
        snmp = self._get_snmp()
        destinations = []
        
        try:
            # Walk the row status to find configured destinations
            results = await snmp.bulk_walk(self.OID_BULK_CFG_ROW_STATUS, max_repetitions=20)
            
            if not results:
                return {"success": True, "destinations": []}
            
            for var_bind in results:
                oid_str = str(var_bind[0])
                row_status = int(var_bind[1])
                
                # Only include active rows (rowStatus=1)
                if row_status != 1:
                    continue
                
                # Extract index from OID
                dest_index = int(oid_str.split(".")[-1])
                
                # Get destination details
                dest_info = {
                    "index": dest_index,
                    "ip_address": None,
                    "port": 69,
                    "protocol": "tftp",
                    "local_store": True
                }
                
                # Get IP address
                try:
                    ip_result = await snmp.get(f"{self.OID_BULK_CFG_IP_ADDR}.{dest_index}")
                    if ip_result:
                        ip_bytes = ip_result[0][1]
                        if hasattr(ip_bytes, 'prettyPrint'):
                            ip_hex = ip_bytes.prettyPrint()
                            if ip_hex.startswith("0x"):
                                ip_hex = ip_hex[2:]
                            if len(ip_hex) == 8:
                                dest_info["ip_address"] = ".".join([
                                    str(int(ip_hex[i:i+2], 16)) for i in range(0, 8, 2)
                                ])
                except Exception:
                    pass
                
                # Get port
                try:
                    port_result = await snmp.get(f"{self.OID_BULK_CFG_PORT}.{dest_index}")
                    if port_result:
                        dest_info["port"] = int(port_result[0][1])
                except Exception:
                    pass
                
                # Get local store setting
                try:
                    ls_result = await snmp.get(f"{self.OID_BULK_CFG_LOCAL_STORE}.{dest_index}")
                    if ls_result:
                        dest_info["local_store"] = int(ls_result[0][1]) == 1
                except Exception:
                    pass
                
                destinations.append(dest_info)
            
            return {"success": True, "destinations": destinations}
            
        except Exception as e:
            self.logger.error(f"Failed to get bulk destinations: {e}")
            return {"success": False, "error": str(e), "destinations": []}
