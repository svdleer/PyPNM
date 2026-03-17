# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Service for CMTS Upstream OFDMA RxMER operations.

This module provides async methods for CMTS-side US OFDMA RxMER
measurements using agent-routed SNMP for CMTS communication.

OIDs used (from DOCS-PNM-MIB):
- docsIf3CmtsCmRegStatusMacAddr: 1.3.6.1.4.1.4491.2.1.20.1.3.1.2
- docsIf31CmtsCmUsOfdmaChannelStatus: 1.3.6.1.4.1.4491.2.1.28.1.4.1.2
- docsPnmCmtsUsOfdmaRxMerTable: 1.3.6.1.4.1.4491.2.1.27.1.3.7
- docsIf3CmtsCmUsStatusEqData: 1.3.6.1.4.1.4491.2.1.20.1.4.2.1.5 (ATDMA pre-EQ)
"""

from __future__ import annotations

import logging
import re
from enum import IntEnum
from typing import Any, Dict, Optional

from pypnm.api.agent.manager import get_agent_manager
from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData
from pypnm.lib.types import BandwidthHz


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
    - Managing bulk data transfer destinations
    
    All SNMP operations are routed through the agent.
    """
    
    # OID definitions
    OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
    OID_CM_REG_MAC = "1.3.6.1.2.1.10.127.1.3.3.1.2"  # docsIfCmtsCmStatusMacAddress (works on E6000)
    OID_CM_OFDMA_STATUS = "1.3.6.1.4.1.4491.2.1.28.1.4.1.2"  # docsIf31CmtsCmUsOfdmaChannelTimingOffset (has cm_index.ofdma_ifindex)
    
    # Pre-equalization data (ATDMA upstream)
    # OID: docsIf3CmtsCmUsStatusEqData.{cm_index}.{us_ifindex} → OCTET STRING (coefficients)
    OID_CM_US_EQ_DATA = "1.3.6.1.4.1.4491.2.1.20.1.4.1.6"  # docsIf3CmtsCmUsStatusEqData
    
    # US OFDMA RxMER Table (docsPnmCmtsUsOfdmaRxMerTable)
    # OID base: 1.3.6.1.4.1.4491.2.1.27.1.3.7.1
    # Column order from DOCS-PNM-MIB (verified with Cisco cBR-8):
    #   .1 = Enable, .2 = CmMac, .3 = PreEq, .4 = NumAvgs, .5 = MeasStatus, .6 = FileName, .7 = DestinationIndex
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

    # Casa CCAP Bulk Data Control Table (docsPnmCcapBulkDataControlTable)
    OID_CCAP_BDT_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1"
    OID_CCAP_BDT_IP_TYPE = f"{OID_CCAP_BDT_TABLE}.2"       # DestIpAddrType
    OID_CCAP_BDT_IP_ADDR = f"{OID_CCAP_BDT_TABLE}.3"       # DestIpAddr
    OID_CCAP_BDT_DEST_PATH = f"{OID_CCAP_BDT_TABLE}.4"     # DestPath
    OID_CCAP_BDT_UPLOAD_CTRL = f"{OID_CCAP_BDT_TABLE}.5"   # UploadControl
    OID_CCAP_BDT_TEST_SELECTOR = f"{OID_CCAP_BDT_TABLE}.6" # PnmTestSelector
    
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
        self.agent_manager = get_agent_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def close(self):
        """No-op for agent-based service (no persistent connection)."""
        pass

    async def detect_vendor(self) -> str:
        """Detect CMTS vendor via sysDescr.

        Returns: 'casa' | 'e6000' | 'cisco' | 'evo' | 'unknown'
        """
        try:
            result = await self._snmp_get("1.3.6.1.2.1.1.1.0")
            raw = str(result.get('output', ''))
            val = raw.split(' = ', 1)[1].strip() if ' = ' in raw else raw.strip()
            if val.upper().startswith('0X'):
                try:
                    val = bytes.fromhex(val[2:]).decode('utf-8', errors='replace')
                except Exception:
                    pass
            low = val.lower()
            if 'cisco' in low or 'cbr' in low:
                return 'cisco'
            if 'casa' in low:
                return 'casa'
            if 'arris' in low or 'cer_v' in low or 'commscope' in low:
                return 'e6000'
            if 'evo' in low or 'vcmts' in low:
                return 'evo'
            return 'unknown'
        except Exception as e:
            self.logger.warning(f"Vendor detection failed: {e}")
            return 'unknown'
    
    # ============================================
    # Agent SNMP helpers (same pattern as UTSC)
    # ============================================
    
    def _get_agent_id(self) -> Optional[str]:
        """Get cmts-agent ID (cmts_reachable capability). Returns None if no such agent connected."""
        if not self.agent_manager:
            return None
        return self.agent_manager.get_agent_id_for_capability('cmts_reachable')
    
    async def _snmp_get(self, oid: str) -> Dict[str, Any]:
        """Execute SNMP GET via agent."""
        agent_id = self._get_agent_id()
        if not agent_id:
            return {'success': False, 'error': 'No agent available'}
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_get',
                params={
                    'target_ip': self.cmts_ip,
                    'oid': oid,
                    'community': self.community,
                    'timeout': 10
                },
                timeout=30
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            
            if result and result.get('result', {}).get('success'):
                return result['result']
            else:
                error = result.get('result', {}).get('error', 'SNMP get failed') if result else 'Timeout'
                return {'success': False, 'error': error}
        except Exception as e:
            self.logger.exception(f"SNMP GET error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _snmp_walk(self, oid: str, timeout: int = 60) -> Dict[str, Any]:
        """Execute SNMP WALK via agent."""
        agent_id = self._get_agent_id()
        if not agent_id:
            return {'success': False, 'error': 'No agent available'}
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_walk',
                params={
                    'target_ip': self.cmts_ip,
                    'oid': oid,
                    'community': self.community,
                    'timeout': 30,   # SNMP PDU timeout; outer timeout governs total walk
                },
                timeout=timeout
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=timeout)
            
            if result and result.get('result', {}).get('success'):
                return result['result']
            else:
                error = result.get('result', {}).get('error', 'SNMP walk failed') if result else 'Timeout'
                return {'success': False, 'error': error}
        except Exception as e:
            self.logger.exception(f"SNMP WALK error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _snmp_set(self, oid: str, value: Any, value_type: str = 'i') -> Dict[str, Any]:
        """Execute SNMP SET via agent (uses write_community).
        
        Agent type codes: 'i'=Integer32, 'u'=Unsigned32, 'g'=Gauge32,
                         's'=OctetString, 'x'=hex OctetString
        """
        agent_id = self._get_agent_id()
        if not agent_id:
            return {'success': False, 'error': 'No agent available'}
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_set',
                params={
                    'target_ip': self.cmts_ip,
                    'oid': oid,
                    'value': value,
                    'type': value_type,  # Agent reads params['type']
                    'community': self.write_community,
                    'timeout': 10
                },
                timeout=30
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            
            if result and result.get('result', {}).get('success'):
                return result['result']
            else:
                error = result.get('result', {}).get('error', 'SNMP set failed') if result else 'Timeout'
                return {'success': False, 'error': error}
        except Exception as e:
            self.logger.exception(f"SNMP SET error: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _parse_ip_from_octetstring(raw: str) -> Optional[str]:
        """Convert a raw SNMP OctetString value to a dotted-decimal IP string.

        Handles all formats the agent may return:
          - Already dotted-decimal: "172.16.6.1"
          - 0x-prefixed hex:        "0xac10060d"  or  "0xAC 10 06 0D"
          - Bare hex string:        "ac10060d"
          - Hex with spaces/colons: "ac:10:06:0d"
        """
        if not raw:
            return None
        raw = raw.strip()

        # Already dotted-decimal (IpAddress type)
        parts = raw.split('.')
        if len(parts) == 4:
            try:
                octets = [int(p) for p in parts]
                if all(0 <= o <= 255 for o in octets):
                    return raw
            except ValueError:
                pass

        # Strip 0x prefix and any whitespace/colons to get bare hex
        hex_str = raw
        if hex_str.lower().startswith('0x'):
            hex_str = hex_str[2:]
        hex_str = hex_str.replace(' ', '').replace(':', '')
        if len(hex_str) == 8:
            try:
                return '.'.join(str(int(hex_str[i:i+2], 16)) for i in range(0, 8, 2))
            except ValueError:
                pass

        return None

    def _parse_get_value(self, result: Dict[str, Any]) -> Optional[str]:
        """Parse value from agent SNMP GET response.
        
        Agent returns either:
        - {'success': True, 'output': 'OID = value'}
        - {'success': True, 'results': [{'oid': ..., 'value': ...}]}
        
        Returns None for SNMP error strings such as 'No Such Instance',
        'No Such Object', or 'No more variables' so callers always receive
        either a real value or None.
        """
        _SNMP_ERROR_STRINGS = (
            'no such instance',
            'no such object',
            'no more variables',
            'end of mib view',
        )

        if not result.get('success'):
            return None

        # Try results array first (walk-style response)
        if result.get('results'):
            value = str(result['results'][0].get('value', ''))
            if value.lower().startswith(_SNMP_ERROR_STRINGS):
                return None
            return value

        # Parse output string (get-style response)
        output = result.get('output', '')
        if ' = ' in output:
            value = output.split(' = ', 1)[1].strip()
        else:
            value = output.strip()
        if not value or value.lower().startswith(_SNMP_ERROR_STRINGS):
            return None
        return value
    
    @staticmethod
    def normalize_mac(mac_address: str) -> str:
        """Normalize MAC address to uppercase colon-separated format.
        
        Agent returns MACs as 'C8:B5:AD:3A:9D:C7' (uppercase, colon-separated).
        """
        mac = mac_address.upper().replace("-", ":").replace(".", "")
        if ":" not in mac:
            mac = ":".join([mac[i:i+2] for i in range(0, 12, 2)])
        return mac
    
    @staticmethod
    def mac_to_hex_string(mac_address: str) -> str:
        """Convert MAC address to hex string for agent SNMP SET (type='x')."""
        return mac_address.upper().replace(":", "").replace("-", "").replace(".", "")
    
    # ============================================
    # OFDMA Discovery
    # ============================================
    
    async def discover_cm_index(self, cm_mac: str) -> Optional[int]:
        """
        Find CM index on CMTS from MAC address.
        
        Args:
            cm_mac: Cable modem MAC address
            
        Returns:
            CM index (docsIf3CmtsCmRegStatusIndex) or None
        """
        mac_normalized = self.normalize_mac(cm_mac)
        
        self.logger.info(f"Looking for CM MAC {mac_normalized} on CMTS {self.cmts_ip}")
        
        try:
            result = await self._snmp_walk(self.OID_CM_REG_MAC, timeout=60)
            
            if not result.get('success') or not result.get('results'):
                self.logger.warning("No CM registration entries found")
                return None
            
            for entry in result['results']:
                oid_str = str(entry.get('oid', ''))
                value = str(entry.get('value', ''))
                
                # Agent returns MAC addresses as "C8:B5:AD:3A:9D:C7" (uppercase colon-sep)
                # for 6-byte OctetStrings via _parse_snmp_value
                found_mac = self.normalize_mac(value)
                
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
    
    async def discover_ofdma_ifindex(self, cm_index: int) -> list[int]:
        """
        Find all active OFDMA channel ifIndexes for a cable modem.

        Uses vendor-agnostic detection: checks timing offset value from
        docsIf31CmtsCmUsOfdmaChannelTimingOffset table. A non-zero value
        indicates an active OFDMA channel regardless of vendor.

        This works for all DOCSIS 3.1 CMTS vendors:
        - Cisco cBR-8: ifIndexes ~488334 (timing offset > 0 when active)
        - CommScope E6000: ifIndexes ~843087xxx (timing offset > 0 when active)
        - Casa CMTS: Similar to CommScope

        Args:
            cm_index: CM registration index

        Returns:
            List of active OFDMA channel ifIndexes (may be empty)
        """
        self.logger.info(f"Looking for OFDMA channels for CM index {cm_index}")

        try:
            result = await self._snmp_walk(self.OID_CM_OFDMA_STATUS, timeout=60)

            if not result.get('success') or not result.get('results'):
                self.logger.warning("No OFDMA status entries found on CMTS")
                return []

            # OID format: <base>.<cmIndex>.<ofdmaIfIndex>
            # Parse suffix relative to base to avoid false matches on small
            # cm_index values (e.g. 1) appearing in the base OID prefix itself.
            base = self.OID_CM_OFDMA_STATUS.rstrip(".")
            found: list[int] = []

            for entry in result['results']:
                oid_str = str(entry.get('oid', ''))
                value = str(entry.get('value', ''))

                # Strip base prefix to get the suffix: <cmIndex>.<ofdmaIfIndex>
                if oid_str.startswith(base + "."):
                    suffix = oid_str[len(base) + 1:]  # e.g. "1.843087877"
                    parts = suffix.split(".")
                    if len(parts) >= 2 and parts[0] == str(cm_index):
                        ofdma_ifindex = int(parts[1])
                        try:
                            timing_offset = int(value)
                            if timing_offset > 0:
                                self.logger.info(f"Found OFDMA ifIndex: {ofdma_ifindex} (timing offset: {timing_offset})")
                                found.append(ofdma_ifindex)
                        except (ValueError, TypeError):
                            pass

            if not found:
                self.logger.warning(f"No OFDMA channels found for CM index {cm_index}")
            return found

        except Exception as e:
            self.logger.error(f"Error discovering OFDMA ifIndex: {e}")
            return []
    
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

        ofdma_ifindexes = await self.discover_ofdma_ifindex(cm_index)
        if not ofdma_ifindexes:
            return {
                "success": False,
                "error": "No OFDMA channel for this modem",
                "cm_mac_address": cm_mac,
                "cm_index": cm_index
            }

        # Resolve description for each channel
        ofdma_channels = []
        for ifindex in ofdma_ifindexes:
            description = None
            try:
                result = await self._snmp_get(f"{self.OID_IF_DESCR}.{ifindex}")
                value = self._parse_get_value(result)
                if value:
                    description = value
            except Exception:
                pass
            ofdma_channels.append({"ifindex": ifindex, "description": description})

        return {
            "success": True,
            "cm_mac_address": cm_mac,
            "cm_index": cm_index,
            # keep legacy single-value field for backwards compat
            "ofdma_ifindex": ofdma_channels[0]["ifindex"],
            "ofdma_description": ofdma_channels[0]["description"],
            "ofdma_channels": ofdma_channels,
        }
    
    # ============================================
    # Pre-Equalization / Group Delay
    # ============================================
    
    async def get_preeq_data(
        self,
        cm_index: int,
        channel_width_hz: int = 6_400_000,  # Default: 6.4 MHz ATDMA
    ) -> dict[str, Any]:
        """
        Get pre-equalization coefficients and group delay for a cable modem.
        
        Queries docsIf3CmtsCmUsStatusEqData and computes group delay from the
        ATDMA upstream pre-equalization coefficients.
        
        Args:
            cm_index: CM registration index from docsIf3CmtsCmRegStatusMacAddr
            channel_width_hz: ATDMA channel width in Hz (default 6.4 MHz)
            
        Returns:
            Dict with pre-EQ metrics and group delay per upstream channel
        """
        self.logger.info(f"Getting pre-EQ data for CM index {cm_index}")
        
        try:
            # Walk pre-EQ data for this CM index — full table across all modems, allow 120 s
            result = await self._snmp_walk(self.OID_CM_US_EQ_DATA, timeout=120)
            
            if not result.get('success') or not result.get('results'):
                self.logger.warning("No pre-EQ data found on CMTS")
                return {"success": False, "error": "No pre-EQ data found", "cm_index": cm_index}
            
            # OID format: <base>.<cm_index>.<us_ifindex>
            base = self.OID_CM_US_EQ_DATA.rstrip(".")
            eq_parser = DocsEqualizerData()
            channels_found = []
            
            for entry in result['results']:
                oid_str = str(entry.get('oid', ''))
                value = entry.get('value', '')
                
                # Parse suffix to get cm_index.us_ifindex
                if oid_str.startswith(base + "."):
                    suffix = oid_str[len(base) + 1:]
                    parts = suffix.split(".")
                    if len(parts) >= 2 and parts[0] == str(cm_index):
                        us_ifindex = int(parts[1])
                        
                        # Value is hex string like "0x08011800..." or "08 01 18 00..."
                        hex_str = str(value)
                        if hex_str.lower().startswith('0x'):
                            hex_str = hex_str[2:]
                        # Remove spaces/colons
                        hex_str = hex_str.replace(' ', '').replace(':', '')
                        
                        if hex_str and len(hex_str) >= 8:  # At least header
                            try:
                                eq_parser.add(
                                    us_ifindex,
                                    hex_str,
                                    channel_width_hz=BandwidthHz(channel_width_hz),
                                )
                                channels_found.append(us_ifindex)
                            except Exception as e:
                                self.logger.warning(f"Failed to parse pre-EQ for ifindex {us_ifindex}: {e}")
            
            if not eq_parser.coefficients_found():
                return {
                    "success": False,
                    "error": "Pre-EQ data found but failed to parse",
                    "cm_index": cm_index,
                }
            
            # Build response with parsed data
            channel_data = []
            for us_ifindex, eq_model in eq_parser.equalizer_data.items():
                ch_info = {
                    "us_ifindex": us_ifindex,
                    "num_taps": eq_model.num_taps,
                    "main_tap_location": eq_model.main_tap_location,
                    "taps_per_symbol": eq_model.taps_per_symbol,
                    "taps": [
                        {"real": t.real, "imag": t.imag, "magnitude": round(t.magnitude, 4)}
                        for t in eq_model.taps
                    ],
                }
                
                # Add metrics if available
                if eq_model.metrics:
                    ch_info["metrics"] = {
                        "main_tap_ratio": eq_model.metrics.main_tap_ratio,
                        "mtc_dB": eq_model.metrics.main_tap_compression,
                        "nmter_dB": eq_model.metrics.non_main_tap_energy_ratio,
                        "pre_main_tap_energy_ratio": eq_model.metrics.pre_main_tap_total_energy_ratio,
                        "post_main_tap_energy_ratio": eq_model.metrics.post_main_tap_total_energy_ratio,
                    }
                
                # Add group delay if available
                if eq_model.group_delay:
                    gd = eq_model.group_delay
                    # Compute peak-to-peak and RMS group delay variation
                    delay_us_list = gd.delay_us
                    if delay_us_list:
                        gd_min = min(delay_us_list)
                        gd_max = max(delay_us_list)
                        gd_mean = sum(delay_us_list) / len(delay_us_list)
                        gd_pp = gd_max - gd_min
                        gd_rms = (sum((d - gd_mean)**2 for d in delay_us_list) / len(delay_us_list)) ** 0.5
                    else:
                        gd_min = gd_max = gd_mean = gd_pp = gd_rms = 0.0
                    
                    ch_info["group_delay"] = {
                        "channel_width_hz": int(gd.channel_width_hz),
                        "symbol_rate": gd.symbol_rate,
                        "symbol_time_us": gd.symbol_time_us,
                        "sample_period_us": gd.sample_period_us,
                        "fft_size": gd.fft_size,
                        "delay_us": delay_us_list[:32] if len(delay_us_list) > 32 else delay_us_list,  # Truncate for response
                        "delay_min_us": round(gd_min, 4),
                        "delay_max_us": round(gd_max, 4),
                        "delay_pp_us": round(gd_pp, 4),
                        "delay_rms_us": round(gd_rms, 4),
                    }
                
                # Add tap delay summary if available
                if eq_model.tap_delay_summary:
                    tds = eq_model.tap_delay_summary
                    # Find cable length equivalents from annotated taps (use first cable type: hardline)
                    pre_main_cable_ft = None
                    post_main_cable_ft = None
                    for tap in tds.taps:
                        if tap.cable_delays:  # Get first cable type (hardline)
                            echo_ft = tap.cable_delays[0].echo_length_ft
                            if tap.tap_offset < 0:
                                if pre_main_cable_ft is None or echo_ft > pre_main_cable_ft:
                                    pre_main_cable_ft = echo_ft
                            elif tap.tap_offset > 0:
                                if post_main_cable_ft is None or echo_ft > post_main_cable_ft:
                                    post_main_cable_ft = echo_ft
                    
                    ch_info["tap_delay_summary"] = {
                        "main_tap_index": tds.main_tap_index,
                        "main_echo_tap_index": tds.main_echo_tap_index,
                        "main_echo_tap_offset": tds.main_echo_tap_offset,
                        "pre_main_cable_ft": round(pre_main_cable_ft, 1) if pre_main_cable_ft else None,
                        "post_main_cable_ft": round(post_main_cable_ft, 1) if post_main_cable_ft else None,
                    }
                
                channel_data.append(ch_info)
            
            return {
                "success": True,
                "cm_index": cm_index,
                "num_channels": len(channel_data),
                "channels": channel_data,
            }
            
        except Exception as e:
            self.logger.error(f"Error getting pre-EQ data: {e}")
            return {"success": False, "error": str(e), "cm_index": cm_index}
    
    # ============================================
    # US OFDMA RxMER Measurement
    # ============================================
    
    async def start_measurement(
        self,
        ofdma_ifindex: int,
        cm_mac: str,
        filename: str = "us_rxmer",
        pre_eq: bool = True,
        num_averages: int = 1,
        destination_index: int = 0,
        tftp_server: Optional[str] = None,
        dest_path: str = "./"
    ) -> dict[str, Any]:
        """
        Start Upstream OFDMA RxMER measurement.

        Follows the exact Cisco cBR-8 flow:
          1. createAndGo bulk destination row (with BaseUri)
          2. Set CmMac, FileName
          3. Set DestinationIndex (Unsigned32, index of bulk dest row)
          4. Set Enable=true

        Args:
            ofdma_ifindex: OFDMA channel ifIndex
            cm_mac: Cable modem MAC address
            filename: Output filename
            pre_eq: Enable pre-equalization
            num_averages: Number of averages
            destination_index: Bulk transfer destination index (0=auto-create row 1)
            tftp_server: TFTP server IP for bulk upload

        Returns:
            Dict with success status and details
        """
        idx = f".{ofdma_ifindex}"

        self.logger.info(
            f"Starting US RxMER for OFDMA ifIndex {ofdma_ifindex}, CM MAC {cm_mac}, "
            f"dest={destination_index}, tftp={tftp_server}"
        )

        try:
            # 0. Detect vendor for BDT routing
            vendor = await self.detect_vendor()
            self.logger.info(f"Detected vendor: {vendor}")

            # 1. Set up bulk destination — vendor-specific
            if vendor == 'casa':
                # Casa uses docsPnmCcapBulkDataControlTable (direct SETs)
                # DestinationIndex is read-only on Casa — read it back
                dest_idx_result = await self._snmp_get(f"{self.OID_US_RXMER_DEST_INDEX}.{ofdma_ifindex}")
                dest_idx_val = self._parse_get_value(dest_idx_result)
                bdt_row = int(dest_idx_val) if dest_idx_val and int(dest_idx_val) > 0 else 1
                self.logger.info(f"Casa DestinationIndex (readback) = {bdt_row}")
                await self._configure_bdt_casa(bdt_row, tftp_server or '', dest_path)
                destination_index = bdt_row
            else:
                # E6000/Cisco: docsPnmBulkDataTransferCfgTable (createAndGo/createAndWait)
                # Reuse an explicitly supplied destination_index (e.g. fiber-node scan
                # primes BDT once before looping over many captures). Reprovision only
                # when caller did not provide an index.
                if tftp_server and destination_index <= 0:
                    try:
                        _dest_idx = 1
                        dest_result = await self.create_bulk_destination(
                            tftp_ip=tftp_server, dest_index=_dest_idx, dest_path=dest_path,
                            vendor=vendor
                        )
                        destination_index = dest_result.get("destination_index", _dest_idx)
                    except Exception as e:
                        self.logger.warning(f"Bulk dest setup failed (continuing): {e}")
                        if destination_index == 0:
                            destination_index = 1
                elif destination_index > 0:
                    self.logger.info(
                        f"Reusing preconfigured bulk destination index {destination_index} (no reprovision)"
                    )

            # 2. Set CM MAC address (CMTS uses this to identify the modem)
            mac_hex = self.mac_to_hex_string(cm_mac)
            await self._snmp_set(f"{self.OID_US_RXMER_CM_MAC}{idx}", mac_hex, 'x')

            # 3. Set filename
            await self._snmp_set(f"{self.OID_US_RXMER_FILENAME}{idx}", filename, 's')

            # 4. Set pre-equalization (1=true, 2=false)
            pre_eq_val = 1 if pre_eq else 2
            await self._snmp_set(f"{self.OID_US_RXMER_PRE_EQ}{idx}", pre_eq_val, 'i')

            # 5. Set number of averages (Gauge32)
            await self._snmp_set(f"{self.OID_US_RXMER_NUM_AVGS}{idx}", num_averages, 'g')

            # 6. Set DestinationIndex — Unsigned32 ('u') required by Cisco cBR-8
            #    Casa manages this internally (read-only) — skip
            if vendor != 'casa':
                await self._snmp_set(f"{self.OID_US_RXMER_DEST_INDEX}{idx}", destination_index, 'u')

            # 7. Enable measurement (triggers capture)
            await self._snmp_set(f"{self.OID_US_RXMER_ENABLE}{idx}", 1, 'i')

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
            Dict with measurement status and filename
        """
        try:
            result = await self._snmp_get(f"{self.OID_US_RXMER_MEAS_STATUS}.{ofdma_ifindex}")
            value = self._parse_get_value(result)
            
            if value is None:
                # Row doesn't exist yet (No Such Instance / no active measurement).
                # Treat as INACTIVE rather than an error — the row is created on first
                # start_measurement() call, so absence means no measurement running.
                snmp_err = result.get('error')
                if snmp_err:
                    return {"success": False, "error": snmp_err}
                return {
                    "success": True,
                    "ofdma_ifindex": ofdma_ifindex,
                    "meas_status": MeasStatus.INACTIVE,
                    "meas_status_name": "INACTIVE",
                    "is_ready": False,
                    "is_busy": False,
                    "is_error": False,
                }

            # Guard against SNMP "No Such Instance" strings (e.g. Cisco cBR-8
            # returns a text error string instead of None when the row does not
            # exist yet — treat it as INACTIVE so the caller can retry)
            try:
                status_value = int(value)
            except (ValueError, TypeError):
                self.logger.warning(
                    f"US RxMER status OID returned non-integer: {value!r} "
                    f"(treating as INACTIVE)"
                )
                return {
                    "success": True,
                    "ofdma_ifindex": ofdma_ifindex,
                    "meas_status": MeasStatus.INACTIVE,
                    "meas_status_name": "INACTIVE",
                    "is_ready": False,
                    "is_busy": False,
                    "is_error": False,
                }
            status_name = MeasStatus(status_value).name if status_value in [e.value for e in MeasStatus] else "unknown"
            
            response = {
                "success": True,
                "ofdma_ifindex": ofdma_ifindex,
                "meas_status": status_value,
                "meas_status_name": status_name,
                "is_ready": status_value == MeasStatus.SAMPLE_READY,
                "is_busy": status_value == MeasStatus.BUSY,
                "is_error": status_value == MeasStatus.ERROR
            }
            
            # Get filename if measurement is ready
            if status_value == MeasStatus.SAMPLE_READY:
                try:
                    filename_result = await self._snmp_get(f"{self.OID_US_RXMER_FILENAME}.{ofdma_ifindex}")
                    filename_value = self._parse_get_value(filename_result)
                    if filename_value:
                        response["filename"] = filename_value
                        self.logger.info(f"US RxMER ready, filename: {filename_value}")
                except Exception as e:
                    self.logger.warning(f"Failed to get filename: {e}")
            
            return response
            
        except Exception as e:
            self.logger.error(f"Failed to get US RxMER status: {e}")
            return {"success": False, "error": str(e)}
    
    # ============================================
    # Bulk Data Transfer Destinations
    # ============================================
    
    async def get_bulk_destinations(self) -> dict[str, Any]:
        """
        Get list of configured bulk data transfer destinations.
        
        These destinations can be used with destination_index parameter
        in start_measurement() to upload results via TFTP.
        
        Returns:
            Dict with list of configured destinations
        """
        destinations = []
        
        try:
            # Walk the row status to find configured destinations
            result = await self._snmp_walk(self.OID_BULK_CFG_ROW_STATUS)
            
            if not result.get('success') or not result.get('results'):
                return {"success": True, "destinations": []}
            
            for entry in result['results']:
                oid_str = str(entry.get('oid', ''))
                row_status = int(entry.get('value', 0))
                
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
                    ip_result = await self._snmp_get(f"{self.OID_BULK_CFG_IP_ADDR}.{dest_index}")
                    ip_value = self._parse_get_value(ip_result)
                    if ip_value:
                        dest_info["ip_address"] = self._parse_ip_from_octetstring(ip_value)
                except Exception:
                    pass
                
                # Get port
                try:
                    port_result = await self._snmp_get(f"{self.OID_BULK_CFG_PORT}.{dest_index}")
                    port_value = self._parse_get_value(port_result)
                    if port_value:
                        dest_info["port"] = int(port_value)
                except Exception:
                    pass
                
                # Get local store setting
                try:
                    ls_result = await self._snmp_get(f"{self.OID_BULK_CFG_LOCAL_STORE}.{dest_index}")
                    ls_value = self._parse_get_value(ls_result)
                    if ls_value:
                        dest_info["local_store"] = int(ls_value) == 1
                except Exception:
                    pass
                
                destinations.append(dest_info)
            
            return {"success": True, "destinations": destinations}
            
        except Exception as e:
            self.logger.error(f"Failed to get bulk destinations: {e}")
            return {"success": False, "error": str(e), "destinations": []}

    async def _configure_bdt_casa(self, row: int, tftp_ip: str, dest_path: str = "./"):
        """Configure Casa CCAP BDT (docsPnmCcapBulkDataControlTable).

        Casa CCAP table has NO RowStatus — just SET columns directly.
        PnmTestSelector bit5 (0x0400) = usOfdmaRxMer.
        """
        import ipaddress
        ip_hex = ipaddress.ip_address(tftp_ip).packed.hex().upper()
        ip_hex_formatted = ' '.join([ip_hex[i:i+2] for i in range(0, len(ip_hex), 2)])

        self.logger.info(f"Casa CCAP BDT row {row}: TFTP {tftp_ip}, path={dest_path}")

        await self._snmp_set(f"{self.OID_CCAP_BDT_IP_TYPE}.{row}", 1, 'i')          # ipv4
        await self._snmp_set(f"{self.OID_CCAP_BDT_IP_ADDR}.{row}", ip_hex_formatted, 'x')
        await self._snmp_set(f"{self.OID_CCAP_BDT_DEST_PATH}.{row}", dest_path, 's')
        await self._snmp_set(f"{self.OID_CCAP_BDT_UPLOAD_CTRL}.{row}", 3, 'i')      # autoUpload
        # PnmTestSelector: bit5 = usOfdmaRxMer (0x04 0x00)
        await self._snmp_set(f"{self.OID_CCAP_BDT_TEST_SELECTOR}.{row}", "04 00", 'x')

        self.logger.info(f"Casa CCAP BDT row {row} configured for US RxMER")

    async def create_bulk_destination(
        self,
        tftp_ip: str,
        port: int = 69,
        local_store: bool = False,
        dest_index: Optional[int] = None,
        dest_path: str = "./",
        vendor: str = '',
    ) -> dict[str, Any]:
        """
        Create or update a bulk data transfer destination for TFTP uploads.
        
        Args:
            tftp_ip: TFTP server IP address
            port: TFTP port (default 69)
            local_store: Also store locally on CMTS (default True)
            dest_index: Destination index to use (1-10). If None, finds first available.
            
        Returns:
            Dict with success status and destination_index
        """
        try:
            # If no index specified, find first available (1-10)
            if dest_index is None:
                for idx in range(1, 11):
                    try:
                        result = await self._snmp_get(f"{self.OID_BULK_CFG_ROW_STATUS}.{idx}")
                        value = self._parse_get_value(result)
                        if value:
                            row_status = int(value)
                            # Check if this destination already points to our TFTP server
                            if row_status == 1:
                                ip_result = await self._snmp_get(f"{self.OID_BULK_CFG_IP_ADDR}.{idx}")
                                ip_value = self._parse_get_value(ip_result)
                                if ip_value:
                                    existing_ip = self._parse_ip_from_octetstring(ip_value)
                                    if existing_ip == tftp_ip:
                                        # Also check DestBaseUri — it may contain a stale host
                                        # from a previous misconfiguration (e.g. old alt-TFTP IP).
                                        # If the URI references a different host, destroy the row
                                        # and fall through to recreate it cleanly.
                                        uri_stale = False
                                        try:
                                            uri_result = await self._snmp_get(f"{self.OID_BULK_CFG_BASE_URI}.{idx}")
                                            uri_value = str(self._parse_get_value(uri_result) or '')
                                            if uri_value and tftp_ip not in uri_value and '://' in uri_value:
                                                self.logger.warning(
                                                    f"Bulk dest {idx} IP matches but BaseUri '{uri_value}' "
                                                    f"references different host — destroying and recreating row"
                                                )
                                                uri_stale = True
                                        except Exception:
                                            pass

                                        if uri_stale:
                                            try:
                                                await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{idx}", 6, 'i')  # destroy
                                            except Exception:
                                                pass
                                            dest_index = idx
                                            break

                                        # Always destroy and recreate — avoids silent
                                        # notInService failures on Cisco cBR-8.
                                        self.logger.info(f"Existing TFTP dest {idx} matches — destroying and recreating")
                                        try:
                                            await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{idx}", 6, 'i')  # destroy
                                        except Exception:
                                            pass
                                        dest_index = idx
                                        break
                            # Row doesn't exist or is empty
                            if row_status in (0, 2, 6):  # notInService, destroy, notReady
                                dest_index = idx
                                break
                        else:
                            dest_index = idx
                            break
                    except Exception:
                        dest_index = idx
                        break
                
                if dest_index is None:
                    dest_index = 1  # Default to index 1
            
            # Auto-detect vendor when not supplied
            if not vendor:
                try:
                    raw = await self._snmp_get('1.3.6.1.2.1.1.1.0')
                    descr = str(raw.get('output', '') if isinstance(raw, dict) else raw).upper()
                    if 'CISCO' in descr:
                        vendor = 'cisco'
                    elif 'ARRIS' in descr or 'COMMSCOPE' in descr:
                        vendor = 'arris'
                    elif 'CASA' in descr:
                        vendor = 'casa'
                    self.logger.info(f"BDT auto-detected vendor: {vendor}")
                except Exception:
                    pass

            self.logger.info(f"Creating bulk destination at index {dest_index} for TFTP {tftp_ip}:{port} vendor={vendor}")

            import asyncio

            # Convert IP to hex bytes for OctetString SET
            ip_parts = tftp_ip.split(".")
            ip_hex = "".join([f"{int(p):02x}" for p in ip_parts])

            # Normalise dest_path once for use below
            _path = re.sub(r'^(\./)+'  , '', dest_path).lstrip('/')
            if _path and not _path.endswith('/'):
                _path += '/'

            # DestBaseUri value depends on vendor:
            # - Cisco cBR-8: full URI  tftp://ip/path
            # - Arris/CommScope: path only  e.g. "access/pnmupload/"
            _full_uri = f"tftp://{tftp_ip}/{_path}"
            _uri_value = _full_uri if vendor == 'cisco' else (_path or _full_uri)

            # Step 1: destroy existing row (ignore errors — row may not exist)
            try:
                await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{dest_index}", 6, 'i')
            except Exception:
                pass
            await asyncio.sleep(1)

            # Step 2: vendor-aware row creation
            if vendor == 'cisco':
                # Cisco cBR-8: createAndGo(4), then SET columns on active row
                await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{dest_index}", 4, 'i')
                await asyncio.sleep(1)

                await self._snmp_set(f"{self.OID_BULK_CFG_IP_TYPE}.{dest_index}", 1, 'i')
                await self._snmp_set(f"{self.OID_BULK_CFG_IP_ADDR}.{dest_index}", ip_hex, 'x')
                if _uri_value:
                    await self._snmp_set(f"{self.OID_BULK_CFG_BASE_URI}.{dest_index}", _uri_value, 's')
                    self.logger.info(f"Set BaseUri for destination {dest_index}: '{_uri_value}'")
                # Protocol NOT set — Cisco defaults to tftp, explicit SET causes genError
                # LocalStore: read-only on Cisco (notWritable)
            else:
                # Arris/CommScope/Casa: createAndWait(5), SET columns, then activate
                await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{dest_index}", 5, 'i')

                await self._snmp_set(f"{self.OID_BULK_CFG_IP_TYPE}.{dest_index}", 1, 'i')
                await self._snmp_set(f"{self.OID_BULK_CFG_IP_ADDR}.{dest_index}", ip_hex, 'x')
                # Protocol = tftp(1) — E6000/Arris requires explicit SET
                try:
                    await self._snmp_set(f"{self.OID_BULK_CFG_PROTOCOL}.{dest_index}", 1, 'i')
                except Exception:
                    pass
                if _uri_value:
                    await self._snmp_set(f"{self.OID_BULK_CFG_BASE_URI}.{dest_index}", _uri_value, 's')
                    self.logger.info(f"Set BaseUri for destination {dest_index}: '{_uri_value}'")
                # LocalStore: not always writable — wrap
                try:
                    await self._snmp_set(f"{self.OID_BULK_CFG_LOCAL_STORE}.{dest_index}", 2 if not local_store else 1, 'i')
                except Exception:
                    pass
                # Activate
                await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{dest_index}", 1, 'i')

            # Poll RowStatus until active(1)
            for _attempt in range(5):
                await asyncio.sleep(1)
                probe = await self._snmp_get(f"{self.OID_BULK_CFG_ROW_STATUS}.{dest_index}")
                raw_rs = str(probe.get('output', '') or '')
                val = raw_rs.split('=', 1)[-1].strip() if '=' in raw_rs else raw_rs.strip()
                if val in ('1', 'active'):
                    self.logger.info(f"BDT row {dest_index} confirmed active after {_attempt + 1}s")
                    break
                self.logger.debug(f"BDT row {dest_index} RowStatus={val!r}, retrying...")
            else:
                self.logger.warning(f"BDT row {dest_index} did not confirm active after 5s — proceeding anyway")

            self.logger.info(f"Successfully created bulk destination {dest_index} -> {tftp_ip}:{port}")
            
            return {
                "success": True,
                "destination_index": dest_index,
                "tftp_ip": tftp_ip,
                "port": port,
                "local_store": local_store,
                "message": f"Created destination {dest_index} for {tftp_ip}:{port}",
                "created": True
            }
            
        except Exception as e:
            self.logger.error(f"Failed to create bulk destination: {e}")
            return {"success": False, "error": str(e)}
