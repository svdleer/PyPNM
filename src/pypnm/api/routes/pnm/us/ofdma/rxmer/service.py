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
    
    # ============================================
    # Agent SNMP helpers (same pattern as UTSC)
    # ============================================
    
    def _get_agent_id(self) -> Optional[str]:
        """Get first available agent ID."""
        if not self.agent_manager:
            return None
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return None
        agent = agents[0]
        return agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
    
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
                    'timeout': 15
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
            # Walk pre-EQ data for this CM index
            result = await self._snmp_walk(self.OID_CM_US_EQ_DATA, timeout=30)
            
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
                    ch_info["tap_delay_summary"] = {
                        "main_tap_index": tds.main_tap_index,
                        "max_pre_main_delay_us": tds.max_pre_main_delay_us,
                        "max_post_main_delay_us": tds.max_post_main_delay_us,
                        "pre_main_cable_ft": tds.pre_main_cable_equivalent_ft,
                        "post_main_cable_ft": tds.post_main_cable_equivalent_ft,
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
        tftp_server: Optional[str] = None
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
            # 1. Set up bulk destination row — Cisco requires DestinationIndex to
            #    point at an active row; without it the Enable SET is silently ignored.
            if tftp_server and destination_index == 0:
                try:
                    dest_result = await self.create_bulk_destination(
                        tftp_ip=tftp_server, dest_index=1
                    )
                    destination_index = dest_result.get("destination_index", 1)
                except Exception as e:
                    self.logger.warning(f"Bulk dest setup failed (continuing): {e}")
                    destination_index = 1

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

    async def create_bulk_destination(
        self,
        tftp_ip: str,
        port: int = 69,
        local_store: bool = True,
        dest_index: Optional[int] = None
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
                                        self.logger.info(f"Found existing TFTP destination at index {idx}")
                                        return {
                                            "success": True,
                                            "destination_index": idx,
                                            "message": f"Using existing destination {idx} for {tftp_ip}",
                                            "created": False
                                        }
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
            
            self.logger.info(f"Creating bulk destination at index {dest_index} for TFTP {tftp_ip}:{port}")
            
            # Convert IP to hex bytes for OctetString SET
            ip_parts = tftp_ip.split(".")
            ip_hex = "".join([f"{int(p):02x}" for p in ip_parts])
            
            # Cisco cBR-8 flow: createAndGo(4) activates the row immediately
            await self._snmp_set(f"{self.OID_BULK_CFG_ROW_STATUS}.{dest_index}", 4, 'i')

            # IP address type (1=IPv4)
            await self._snmp_set(f"{self.OID_BULK_CFG_IP_TYPE}.{dest_index}", 1, 'i')

            # IP address (4-byte OctetString, e.g. "ac100884")
            await self._snmp_set(f"{self.OID_BULK_CFG_IP_ADDR}.{dest_index}", ip_hex, 'x')

            # Only set BaseUri for Cisco cBR-8, skip for Arris/CommScope
            if hasattr(self, 'cmts_vendor') and self.cmts_vendor and self.cmts_vendor.lower() == 'cisco':
                base_uri = f"tftp://{tftp_ip}/"
                await self._snmp_set(f"{self.OID_BULK_CFG_BASE_URI}.{dest_index}", base_uri, 's')
            
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
