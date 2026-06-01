# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Service for CMTS Upstream Triggered Spectrum Capture (UTSC) operations.

This module provides async methods for CMTS-side UTSC measurements
using agent-routed SNMP for CMTS communication.

OIDs used (from DOCS-PNM-MIB):
- docsPnmCmtsUtscCfgTable: 1.3.6.1.4.1.4491.2.1.27.1.3.10.2
- docsPnmCmtsUtscCtrlTable: 1.3.6.1.4.1.4491.2.1.27.1.3.10.3
- docsPnmCmtsUtscStatusTable: 1.3.6.1.4.1.4491.2.1.27.1.3.10.4
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any, Dict, Optional

from pypnm.api.agent.manager import get_agent_manager


logger = logging.getLogger(__name__)


class TriggerMode(IntEnum):
    """UTSC Trigger Mode"""
    OTHER = 1
    FREE_RUNNING = 2
    MINI_SLOT_COUNT = 3
    SID = 4
    IUC = 5
    CM_MAC = 6


class OutputFormat(IntEnum):
    """UTSC Output Format
    
    Cisco cBR-8 supports only: TIME_IQ (1) and FFT_POWER (2)
    CommScope E6000 supports: all formats including FFT_AMPLITUDE (5)
    """
    TIME_IQ = 1
    FFT_POWER = 2
    RAW_ADC = 3
    FFT_IQ = 4
    FFT_AMPLITUDE = 5
    FFT_DB = 6


class MeasStatus(IntEnum):
    """Measurement Status"""
    OTHER = 1
    INACTIVE = 2
    BUSY = 3
    SAMPLE_READY = 4
    ERROR = 5
    RESOURCE_UNAVAILABLE = 6
    SAMPLE_TRUNCATED = 7


class CmtsUtscService:
    """
    Service for CMTS Upstream Triggered Spectrum Capture operations.
    
    Provides async methods for:
    - Configuring UTSC test parameters
    - Starting/stopping UTSC tests
    - Getting UTSC status
    - Listing available RF ports
    
    All SNMP operations are routed through the agent.
    """
    
    # OID definitions
    OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
    
    # UTSC Config Table (docsPnmCmtsUtscCfgTable) - 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1
    OID_UTSC_CFG_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
    OID_UTSC_CFG_LOGICAL_CH = f"{OID_UTSC_CFG_TABLE}.2"       # LogicalChIfIndex
    OID_UTSC_CFG_TRIGGER_MODE = f"{OID_UTSC_CFG_TABLE}.3"     # TriggerMode
    OID_UTSC_CFG_MINISLOT_COUNT = f"{OID_UTSC_CFG_TABLE}.4"   # MinislotCount
    OID_UTSC_CFG_SID = f"{OID_UTSC_CFG_TABLE}.5"              # Sid
    OID_UTSC_CFG_CM_MAC = f"{OID_UTSC_CFG_TABLE}.6"           # CmMacAddr
    OID_UTSC_CFG_TIMEOUT = f"{OID_UTSC_CFG_TABLE}.7"          # Timeout
    OID_UTSC_CFG_CENTER_FREQ = f"{OID_UTSC_CFG_TABLE}.8"      # CenterFreq (Hz)
    OID_UTSC_CFG_SPAN = f"{OID_UTSC_CFG_TABLE}.9"             # Span (Hz)
    OID_UTSC_CFG_NUM_BINS = f"{OID_UTSC_CFG_TABLE}.10"        # NumBins
    OID_UTSC_CFG_AVG_SAMP = f"{OID_UTSC_CFG_TABLE}.11"        # AvgSamp
    OID_UTSC_CFG_FILENAME = f"{OID_UTSC_CFG_TABLE}.12"        # Filename
    OID_UTSC_CFG_EQUIV_NOISE_BW = f"{OID_UTSC_CFG_TABLE}.13"  # EquivNoiseBandwidth
    OID_UTSC_CFG_RBW = f"{OID_UTSC_CFG_TABLE}.14"             # Rbw
    OID_UTSC_CFG_WINDOW_REJ = f"{OID_UTSC_CFG_TABLE}.15"      # WindowRej
    OID_UTSC_CFG_WINDOW = f"{OID_UTSC_CFG_TABLE}.16"          # Window
    OID_UTSC_CFG_OUTPUT_FORMAT = f"{OID_UTSC_CFG_TABLE}.17"   # OutputFormat
    OID_UTSC_CFG_REPEAT_PERIOD = f"{OID_UTSC_CFG_TABLE}.18"   # RepeatPeriod (us)
    OID_UTSC_CFG_FREERUN_DUR = f"{OID_UTSC_CFG_TABLE}.19"     # FreeRunDuration (ms)
    OID_UTSC_CFG_TRIGGER_COUNT = f"{OID_UTSC_CFG_TABLE}.20"   # TriggerCount
    OID_UTSC_CFG_ROW_STATUS = f"{OID_UTSC_CFG_TABLE}.21"      # RowStatus
    OID_UTSC_CFG_IUC = f"{OID_UTSC_CFG_TABLE}.22"             # Iuc
    OID_UTSC_CFG_DEST_INDEX = f"{OID_UTSC_CFG_TABLE}.24"      # DestinationIndex
    OID_UTSC_CFG_NUM_AVGS = f"{OID_UTSC_CFG_TABLE}.25"        # NumAvgs
    
    # Bulk Data Control Table (docsPnmCcapBulkDataControl) - 1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1
    # Casa-specific CCAP table — used on Casa 100G for UTSC file upload
    # OIDs verified via: snmptranslate -On DOCS-PNM-MIB::docsPnmCcapBulkDataControl*
    OID_BULK_DATA_CTRL_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1"
    OID_BULK_DATA_DEST_IP_TYPE = f"{OID_BULK_DATA_CTRL_TABLE}.2"     # DestIpAddrType
    OID_BULK_DATA_DEST_IP = f"{OID_BULK_DATA_CTRL_TABLE}.3"           # DestIpAddr
    OID_BULK_DATA_DEST_PATH = f"{OID_BULK_DATA_CTRL_TABLE}.4"         # DestPath
    OID_BULK_DATA_UPLOAD_CTRL = f"{OID_BULK_DATA_CTRL_TABLE}.5"       # UploadControl
    OID_BULK_DATA_TEST_SELECTOR = f"{OID_BULK_DATA_CTRL_TABLE}.6"     # PnmTestSelector

    # Standard Bulk Data Transfer Config Table (docsPnmBulkDataTransferCfgTable)
    # Used by E6000/Cisco — fallback when CCAP table is notWritable
    OID_BDT_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"
    OID_BDT_IP_TYPE   = f"{OID_BDT_TABLE}.3"    # DestHostIpAddrType
    OID_BDT_IP_ADDR   = f"{OID_BDT_TABLE}.4"    # DestHostIpAddress
    OID_BDT_BASE_URI  = f"{OID_BDT_TABLE}.6"    # DestBaseUri
    OID_BDT_PROTOCOL  = f"{OID_BDT_TABLE}.7"    # Protocol (1=tftp)
    OID_BDT_ROW_STATUS = f"{OID_BDT_TABLE}.9"   # RowStatus
    
    # UTSC Capability Table - 1.3.6.1.4.1.4491.2.1.27.1.3.10.1.1
    OID_UTSC_CAPAB_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.1.1"
    OID_UTSC_CAPAB_TRIGGER_MODE = f"{OID_UTSC_CAPAB_TABLE}.1"  # Supported trigger modes
    OID_UTSC_CAPAB_OUTPUT_FORMAT = f"{OID_UTSC_CAPAB_TABLE}.2" # Supported output formats
    OID_UTSC_CAPAB_WINDOW = f"{OID_UTSC_CAPAB_TABLE}.3"        # Supported windows
    OID_UTSC_CAPAB_DESCRIPTION = f"{OID_UTSC_CAPAB_TABLE}.4"   # Description
    
    # UTSC Control Table (docsPnmCmtsUtscCtrlTable) - 1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1
    OID_UTSC_CTRL_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1"
    OID_UTSC_CTRL_INITIATE = f"{OID_UTSC_CTRL_TABLE}.1"       # InitiateTest
    
    # UTSC Status Table (docsPnmCmtsUtscStatusTable) - 1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1
    OID_UTSC_STATUS_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1"
    OID_UTSC_STATUS_MEAS = f"{OID_UTSC_STATUS_TABLE}.1"       # MeasStatus
    OID_UTSC_STATUS_AVG_PWR = f"{OID_UTSC_STATUS_TABLE}.2"    # AvgPwr (HundredthsdB)
    
    def __init__(
        self,
        cmts_ip: str,
        community: str = "private",
        write_community: Optional[str] = None
    ):
        """
        Initialize CMTS UTSC service.
        
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
    # Agent SNMP helpers
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
    
    async def _snmp_walk(self, oid: str) -> Dict[str, Any]:
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
                timeout=60
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=60)
            
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
                # notWritable means the CMTS already has this configured and
                # won't allow overwriting — log at DEBUG to avoid alarm fatigue.
                if 'notWritable' in str(error):
                    self.logger.debug(f"SNMP SET notWritable oid={oid} (CMTS pre-configured)")
                else:
                    self.logger.warning(f"SNMP SET failed oid={oid} value={value!r} type={value_type} error={error}")
                return {'success': False, 'error': error}
        except Exception as e:
            self.logger.exception(f"SNMP SET error: {e}")
            return {'success': False, 'error': str(e)}
    
    def _parse_get_value(self, result: Dict[str, Any]) -> Optional[str]:
        """Parse value from agent SNMP GET response.
        
        Agent returns either:
        - {'success': True, 'output': 'OID = value'}
        - {'success': True, 'results': [{'oid': ..., 'value': ...}]}
        """
        if not result.get('success'):
            return None
        
        # Try results array first (walk-style response)
        if result.get('results'):
            return str(result['results'][0].get('value', ''))
        
        # Parse output string (get-style response)
        output = result.get('output', '')
        if ' = ' in output:
            return output.split(' = ', 1)[1].strip()
        return output.strip() if output else None
    
    async def configure_bulk_data_control(
        self,
        dest_ip: str,
        dest_path: str = "./",
        index: int = 1,
        pnm_types: list[str] = None
    ) -> dict[str, Any]:
        """
        Configure bulk data control for Casa CCAP (UTSC file upload).
        
        Sets up row in docsPnmCcapBulkDataControlTable for UTSC file upload:
        - DestIpAddr: TFTP server IP
        - DestPath: Upload path
        - UploadControl: autoUpload(3)
        - PnmTestSelector: bit 8 (usTriggeredSpectrumCapture)
        
        Args:
            dest_ip: TFTP/FTP server IP for file upload
            dest_path: Destination path (default: "./")
            index: Table index (default: 1)
            
        Returns:
            Dict with success status
        """
        if pnm_types is None:
            pnm_types = ['utsc']

        try:
            import asyncio
            import ipaddress

            vendor = await self.detect_vendor()

            self.logger.info(f"Configuring bulk data control for {pnm_types} upload to {dest_ip}:{dest_path}")
            
            # Convert IP to hex string
            ip_obj = ipaddress.ip_address(dest_ip)
            ip_hex = ip_obj.packed.hex()
            ip_hex_formatted = ' '.join([ip_hex[i:i+2] for i in range(0, len(ip_hex), 2)]).upper()

            # Calculate selector before any SETs
            byte0 = 0x00
            byte1 = 0x00
            for t in (pnm_types or ['utsc']):
                t = t.lower()
                if t in ('utsc', 'both'):
                    byte1 |= 0x80  # bit8
                if t in ('rxmer', 'both'):
                    byte0 |= 0x04  # bit5
            selector_hex = f"{byte0:02X} {byte1:02X}"

            # Read current DestIpAddr to check if already configured correctly.
            # Casa CMTS rejects SET on active rows → skip if already set to same values.
            existing_ip = await self._snmp_get(f"{self.OID_BULK_DATA_DEST_IP}.{index}")
            existing_path = await self._snmp_get(f"{self.OID_BULK_DATA_DEST_PATH}.{index}")
            existing_selector = await self._snmp_get(f"{self.OID_BULK_DATA_TEST_SELECTOR}.{index}")

            def _normalize(v):
                if v and isinstance(v, dict):
                    v = v.get('value', '')
                return str(v or '').strip().upper().replace(' ', '').replace('0X', '')

            already_set = (
                _normalize(existing_ip) == ip_hex.upper() and
                str(existing_path.get('value', '') if isinstance(existing_path, dict) else existing_path or '').strip() == dest_path and
                _normalize(existing_selector) == selector_hex.replace(' ', '')
            )

            if already_set:
                self.logger.info(f"Bulk data control already configured correctly for index {index}, skipping SETs")
                return {"success": True, "index": index, "dest_ip": dest_ip, "pnm_test_selector_hex": selector_hex, "skipped": True}

            # Probe with the first SET.  If the CMTS returns notWritable the
            # CCAP table is read-only (E6000/Cisco) — fall through to the
            # standard docsPnmBulkDataTransferCfgTable with destroy+recreate.
            probe = await self._snmp_set(f"{self.OID_BULK_DATA_DEST_IP_TYPE}.{index}", 1, 'i')
            if not probe.get('success') and 'notWritable' in str(probe.get('error', '')):
                self.logger.info(
                    f"CCAP bulk data table is notWritable — using standard BDT table "
                    f"(docsPnmBulkDataTransferCfgTable) with destroy+recreate (vendor={vendor})"
                )
                return await self._configure_bdt_standard(dest_ip, dest_path, index, vendor=vendor)

            # CCAP table is writable (Casa) — direct SETs on columns.
            # Casa CCAP table has NO RowStatus — just overwrite columns directly.
            import asyncio

            self.logger.info(f"CCAP bulk data: direct SET for {dest_ip}:{dest_path}")
            await self._snmp_set(f"{self.OID_BULK_DATA_DEST_IP_TYPE}.{index}", 1, 'i')  # ipv4
            await self._snmp_set(f"{self.OID_BULK_DATA_DEST_IP}.{index}", ip_hex_formatted, 'x')
            await self._snmp_set(f"{self.OID_BULK_DATA_DEST_PATH}.{index}", dest_path, 's')
            await self._snmp_set(f"{self.OID_BULK_DATA_UPLOAD_CTRL}.{index}", 3, 'i')  # autoUpload
            await self._snmp_set(f"{self.OID_BULK_DATA_TEST_SELECTOR}.{index}", selector_hex, 'x')

            self.logger.info(f"Bulk data control configured: selector={selector_hex}")
            return {"success": True, "index": index, "dest_ip": dest_ip, "pnm_test_selector_hex": selector_hex}
            
        except Exception as e:
            self.logger.error(f"Failed to configure bulk data control: {e}")
            return {"success": False, "error": str(e)}

    async def _configure_bdt_standard(
        self,
        dest_ip: str,
        dest_path: str = "./",
        index: int = 1,
        vendor: str = ''
    ) -> dict[str, Any]:
        """Configure standard docsPnmBulkDataTransferCfgTable.

        Delegates to CmtsUsOfdmaRxMerService.create_bulk_destination() —
        single vendor-aware implementation for all PNM types.
        """
        from pypnm.api.routes.pnm.us.ofdma.rxmer.service import CmtsUsOfdmaRxMerService

        rxmer_svc = CmtsUsOfdmaRxMerService(
            cmts_ip=self.cmts_ip,
            community=self.community,
            write_community=self.write_community,
        )
        try:
            result = await rxmer_svc.create_bulk_destination(
                tftp_ip=dest_ip,
                port=69,
                local_store=False,
                dest_index=index,
                dest_path=dest_path,
                vendor=vendor,
            )
            return {
                "success": result.get("success", False),
                "index": result.get("destination_index", index),
                "dest_ip": dest_ip,
                "table": "standard",
            }
        finally:
            rxmer_svc.close()
    
    async def detect_vendor(self) -> str:
        """
        Detect CMTS vendor via sysDescr (1.3.6.1.2.1.1.1.0).

        Returns:
            'casa' | 'arris' | 'cisco' | 'unknown'
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
            val = val.upper()
            if 'DCTS VCCAP' in val or 'CASA DCTS VCCAP' in val:
                return 'evo'
            if 'CASA' in val:
                return 'casa'
            if 'ARRIS' in val or 'COMMSCOPE' in val:
                return 'arris'
            if 'CISCO' in val:
                return 'cisco'
            return 'unknown'
        except Exception as e:
            self.logger.warning(f"Vendor detection failed: {e}")
            return 'unknown'

    @staticmethod
    def mac_to_hex_string(mac_address: str) -> str:
        """Convert MAC address to hex string for agent SNMP SET (type='x')."""
        return mac_address.lower().replace(":", "").replace("-", "").replace(".", "")
    
    # ============================================
    # UTSC Operations
    # ============================================
    
    async def get_bulk_data_control(self) -> list[dict]:
        """
        Read Casa docsPnmCcapBulkDataControlTable entries.
        Returns list of dicts with index, ip_address, dest_path, upload_control,
        pnm_test_selector_hex.
        """
        import ipaddress as _ip
        entries = []
        try:
            result = await self._snmp_walk(self.OID_BULK_DATA_UPLOAD_CTRL)
            if not result.get('success') or not result.get('results'):
                return entries
            for entry in result['results']:
                oid_str = str(entry.get('oid', ''))
                idx = int(oid_str.split('.')[-1])

                ip_raw = None
                try:
                    r = await self._snmp_get(f"{self.OID_BULK_DATA_DEST_IP}.{idx}")
                    ip_raw = self._parse_get_value(r)
                except Exception:
                    pass

                ip_str = None
                if ip_raw:
                    # OctetString returned as hex e.g. "0xac10060d", "ac 10 06 01", "ac10060d"
                    hex_str = ip_raw.strip()
                    if hex_str.lower().startswith('0x'):
                        hex_str = hex_str[2:]
                    hex_str = hex_str.replace(' ', '').replace(':', '')
                    if len(hex_str) == 8:
                        try:
                            ip_str = str(_ip.ip_address(bytes.fromhex(hex_str)))
                        except Exception:
                            ip_str = ip_raw
                    else:
                        ip_str = ip_raw

                selector_raw = None
                try:
                    r = await self._snmp_get(f"{self.OID_BULK_DATA_TEST_SELECTOR}.{idx}")
                    selector_raw = self._parse_get_value(r)
                except Exception:
                    pass

                path_raw = None
                try:
                    r = await self._snmp_get(f"{self.OID_BULK_DATA_DEST_PATH}.{idx}")
                    path_raw = self._parse_get_value(r)
                except Exception:
                    pass

                entries.append({
                    "index": idx,
                    "ip_address": ip_str,
                    "dest_path": path_raw,
                    "pnm_test_selector_hex": selector_raw,
                })
        except Exception as e:
            self.logger.error(f"Failed to read Casa bulk data control table: {e}")
        return entries

    async def list_rf_ports(self) -> dict[str, Any]:
        """
        List available RF ports for UTSC.
        
        First scans the UTSC config table for pre-existing rows.
        If empty (e.g. Cisco cBR-8), falls back to walking ifDescr to
        discover upstream RF channels (Cable*/Upstream*, Integrated-Cable*/US*).
        
        Returns:
            Dict with list of RF ports and their configurations
        """
        rf_ports = []
        
        try:
            # 1. Try UTSC config table first (works on CommScope E6000 where rows are pre-created)
            result = await self._snmp_walk(self.OID_UTSC_CFG_TRIGGER_MODE)

            if result.get('success') and result.get('results'):
                # Collect all (rf_port_ifindex, cfg_index) pairs — keep lowest cfg_index per ifindex
                raw_ports: dict[int, int] = {}  # ifindex -> cfg_index
                for entry in result['results']:
                    oid_str = str(entry.get('oid', ''))
                    suffix = oid_str.split(self.OID_UTSC_CFG_TRIGGER_MODE + ".")[-1]
                    parts = suffix.split(".")
                    if len(parts) >= 2:
                        rf_port_ifindex = int(parts[0])
                        cfg_index = int(parts[1])
                        if rf_port_ifindex not in raw_ports or cfg_index < raw_ports[rf_port_ifindex]:
                            raw_ports[rf_port_ifindex] = cfg_index

                # Resolve descriptions for all ports — each entry is a distinct fiber node.
                # CommScope E6000: one RPS blade serves 2 fiber nodes (us-conn 0, us-conn 1),
                # so both must be returned as separate RF ports.
                for ifindex, cfg_index in raw_ports.items():
                    description = None
                    try:
                        desc_result = await self._snmp_get(f"{self.OID_IF_DESCR}.{ifindex}")
                        desc_value = self._parse_get_value(desc_result)
                        if desc_value:
                            description = desc_value
                    except Exception:
                        pass

                    rf_ports.append({
                        "rf_port_ifindex": ifindex,
                        "cfg_index": cfg_index,
                        "description": description
                    })

            if rf_ports:
                self.logger.info(f"Found {len(rf_ports)} RF ports in UTSC config table")
                return {"success": True, "rf_ports": rf_ports}
            
            # 2. Fallback: discover upstream RF channels from ifDescr
            #    Cisco cBR-8 uses "Cable<slot>/<subslot>/US<port>" or
            #    "Integrated-Cable<slot>/<subslot>/US<port>" or
            #    "Upstream-Cable<slot>/<subslot>" descriptions.
            self.logger.info("UTSC config table empty — falling back to ifDescr scan for upstream RF ports")
            import re
            
            descr_result = await self._snmp_walk(self.OID_IF_DESCR)
            if not descr_result.get('success') or not descr_result.get('results'):
                return {"success": True, "rf_ports": []}
            
            # Patterns for upstream interfaces on various vendors
            us_patterns = [
                re.compile(r'Cable\d+/\d+/US\d+', re.I),                           # Cisco cBR-8 (2-level)
                re.compile(r'Cable\d+/\d+/\d+/US\d+', re.I),                      # Cisco cBR-8 (3-level)
                re.compile(r'Integrated-Cable\d+/\d+/US\d+', re.I),                # Cisco cBR-8 integrated (2-level)
                re.compile(r'Integrated-Cable\d+/\d+/\d+/US\d+', re.I),           # Cisco cBR-8 integrated (3-level)
                re.compile(r'Upstream-Cable\d+', re.I),                             # Cisco legacy
                re.compile(r'us-conn\s+\d+/\d+', re.I),                             # CommScope E6000
                re.compile(r'cable-upstream\s+\d+/\d+\.\d+', re.I),                # Casa / Generic
                re.compile(r'^Upstream Physical Interface\s+\d+/\d+\.\d+', re.I),  # Casa 100G physical (UTSC target)
                re.compile(r'RPHY Upstream Physical Interface', re.I),              # Casa DCTS vCCAP / CommScope Evo
                # Note: OFDMA logical channels excluded - use physical port for UTSC
            ]
            
            # Exclude patterns (ethernet, management, etc)
            exclude_patterns = [
                re.compile(r'ethernet', re.I),
                re.compile(r'management', re.I),
                re.compile(r'loopback', re.I),
                re.compile(r'null', re.I),
            ]
            
            for entry in descr_result['results']:
                oid_str = str(entry.get('oid', ''))
                descr = str(entry.get('value', ''))
                
                if not descr or 'No Such' in descr:
                    continue
                
                # Exclude non-RF interfaces (ethernet, management, etc)
                is_excluded = any(p.search(descr) for p in exclude_patterns)
                if is_excluded:
                    continue
                
                # Check if this is an upstream RF interface
                is_upstream = any(p.search(descr) for p in us_patterns)
                if not is_upstream:
                    continue
                
                # Extract ifIndex from OID
                try:
                    ifindex = int(oid_str.split('.')[-1])
                except (ValueError, IndexError):
                    continue
                
                # Skip logical/virtual channels — only want physical RF ports
                # Cisco logical channels: ifIndex >= 840M, descriptions like "Cable8/0/0-upstream3"
                if ifindex >= 840000000:
                    continue
                
                # Casa: Accept both physical (4M range) and logical OFDMA (16M range)
                # Note: Casa mapping is logical_ifindex = physical_ifindex + 12000000
                # For UTSC, physical ports are preferred but both are listed
                
                rf_ports.append({
                    "rf_port_ifindex": ifindex,
                    "cfg_index": 1,  # Default — row will be created on configure
                    "description": descr
                })
            
            self.logger.info(f"Discovered {len(rf_ports)} upstream RF ports via ifDescr")
            return {"success": True, "rf_ports": rf_ports}
            
        except Exception as e:
            self.logger.error(f"Failed to list RF ports: {e}")
            return {"success": False, "error": str(e), "rf_ports": []}
    
    async def get_config(self, rf_port_ifindex: int, cfg_index: int = 1) -> dict[str, Any]:
        """
        Get current UTSC configuration for an RF port.
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index (usually 1)
            
        Returns:
            Dict with current configuration
        """
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        try:
            config = {
                "success": True,
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
            # Read configuration values
            oid_map = {
                "trigger_mode": (self.OID_UTSC_CFG_TRIGGER_MODE, int),
                "center_freq_hz": (self.OID_UTSC_CFG_CENTER_FREQ, int),
                "span_hz": (self.OID_UTSC_CFG_SPAN, int),
                "num_bins": (self.OID_UTSC_CFG_NUM_BINS, int),
                "output_format": (self.OID_UTSC_CFG_OUTPUT_FORMAT, int),
                "window_function": (self.OID_UTSC_CFG_WINDOW, int),
                "repeat_period_us": (self.OID_UTSC_CFG_REPEAT_PERIOD, int),
                "freerun_duration_ms": (self.OID_UTSC_CFG_FREERUN_DUR, int),
                "trigger_count": (self.OID_UTSC_CFG_TRIGGER_COUNT, int),
                "filename": (self.OID_UTSC_CFG_FILENAME, str),
                "destination_index": (self.OID_UTSC_CFG_DEST_INDEX, int),
                "row_status": (self.OID_UTSC_CFG_ROW_STATUS, int),
            }
            
            for key, (oid_base, converter) in oid_map.items():
                try:
                    result = await self._snmp_get(f"{oid_base}{idx}")
                    value = self._parse_get_value(result)
                    if value is not None and 'No Such' not in str(value):
                        if converter == str:
                            config[key] = value
                        else:
                            config[key] = int(value)
                except Exception:
                    pass
            
            # Add human-readable names
            if "trigger_mode" in config:
                trigger_names = {1: "other", 2: "freeRunning", 3: "minislotCount", 
                                4: "sid", 5: "idleSid", 6: "minislotNumber",
                                7: "cmMac", 8: "quietProbeSymbol"}
                config["trigger_mode_name"] = trigger_names.get(config["trigger_mode"], "unknown")
            
            if "output_format" in config:
                output_names = {1: "timeIq", 2: "fftPower", 3: "rawAdc", 
                               4: "fftIq", 5: "fftAmplitude", 6: "fftDb"}
                config["output_format_name"] = output_names.get(config["output_format"], "unknown")
            
            return config
            
        except Exception as e:
            self.logger.error(f"Failed to get UTSC config: {e}")
            return {"success": False, "error": str(e)}
    
    async def configure(
        self,
        rf_port_ifindex: int,
        cfg_index: int = 1,
        trigger_mode: int = 2,
        cm_mac_address: Optional[str] = None,
        logical_ch_ifindex: Optional[int] = None,
        center_freq_hz: int = 50000000,
        span_hz: int = 80000000,
        num_bins: int = 800,
        output_format: Optional[int] = None,  # None = auto-detect
        window_function: int = 2,
        repeat_period_us: int = 100000,
        freerun_duration_ms: int = 0,  # 0 = auto-calculate
        trigger_count: int = 1,
        filename: str = "utsc",
        destination_index: int = 1,
        auto_clear: bool = True
    ) -> dict[str, Any]:
        """
        Configure UTSC test parameters.
        
        Supports both CommScope E6000 and Cisco cBR-8 CMTS:
        
        **Cisco cBR-8 workflow** (per Cisco PNM documentation):
        1. createAndGo(4) to create config entry
        3. Set CenterFreq, Span, NumBins (Gauge32 type)
        4. Set FreeRunDuration (must be set for config to become Active)
        5. Verify RowStatus = active(1)
        6. InitiateTest to start capture
        
        **Cisco quirks:**
        - CenterFreq, Span, NumBins, RepeatPeriod, FreeRunDuration, TriggerCount
          use Gauge32 (SNMP type 'u'), NOT Integer32
        - OutputFormat: only fftPower(2) and timeIQ(1) supported
        - Window: rectangular(2), hann(3), blackmanHarris(4), hamming(5) only
        - Filename OID NOT supported
        - RepeatPeriod must not exceed FreeRunDuration
        - Max 8 captures per line card, 20 per router
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index (always 1 on Cisco)
            trigger_mode: 1=other, 2=freeRunning, 3=minislotCount, 4=sid,
                         5=idleSid, 6=minislotNumber, 7=cmMac, 8=quietProbeSymbol
            cm_mac_address: CM MAC address (required for trigger_mode=7 cmMac)
            logical_ch_ifindex: Logical channel ifIndex for CM MAC trigger
            center_freq_hz: Center frequency in Hz (default 30MHz)
            span_hz: Frequency span in Hz
            num_bins: Number of FFT bins (800)
            output_format: Output format (None=auto-detect, 1=timeIq, 2=fftPower, 
                          5=fftAmplitude). Auto-detection queries CMTS capabilities.
            window_function: 2=rectangular, 3=hann, 4=blackmanHarris, 5=hamming
            repeat_period_us: Repeat period in microseconds (default 50000=50ms)
            freerun_duration_ms: Free run duration in ms (0=auto-calculate)
            trigger_count: Number of captures per trigger (max 10 on E6000)
            filename: Output filename (ignored on Cisco)
            destination_index: Bulk transfer destination (0=local only)
            auto_clear: Automatically clear stale config before setting new params
            
        Returns:
            Dict with success status
        """
        idx = f".{rf_port_ifindex}.{cfg_index}"

        self.logger.info(f"Configuring UTSC for RF port {rf_port_ifindex}, "
                         f"trigger_mode={trigger_mode}, auto_clear={auto_clear}")
        
        try:
            import asyncio

            # Detect vendor via sysDescr (1.3.6.1.2.1.1.1.0)
            # Casa DCTS:          "CASA DCTS ..."
            # CommScope/Arris E6000: "CER_V... VENDOR: ARRIS ..."
            # Cisco cBR-8:        "Cisco IOS-XE ..." or "CISCO ..."
            sys_descr_result = await self._snmp_get("1.3.6.1.2.1.1.1.0")
            sys_descr_raw = str(sys_descr_result.get('output', ''))
            # Agent output format: "SNMPV2-SMI::MIB-2.1.1.0 = <value>"
            # Extract value after " = "
            if ' = ' in sys_descr_raw:
                sys_descr_val = sys_descr_raw.split(' = ', 1)[1].strip()
            else:
                sys_descr_val = sys_descr_raw.strip()
            # Agent may return hex-encoded string for long OctetStrings (e.g. Cisco cBR-8)
            # Format: "0X436973636F20494F5320536F667477617265..."
            if sys_descr_val.upper().startswith('0X'):
                try:
                    sys_descr = bytes.fromhex(sys_descr_val[2:]).decode('utf-8', errors='replace').upper()
                except Exception:
                    sys_descr = sys_descr_val.upper()
            else:
                sys_descr = sys_descr_val.upper()
            is_evo = 'DCTS VCCAP' in sys_descr  # CommScope EVO vCCAP (sysDescr: 'CASA DCTS VCCAP, HW=CASA-VNF')
            is_casa = 'CASA' in sys_descr and not is_evo  # Casa C100G — exclude EVO which also contains 'CASA'
            is_arris = 'ARRIS' in sys_descr
            is_cisco = 'CISCO' in sys_descr
            vendor = 'casa' if is_casa else ('evo' if is_evo else ('arris' if is_arris else ('cisco' if is_cisco else 'unknown')))
            self.logger.info(f"Vendor detection: {vendor} — sysDescr='{sys_descr[:80]}'")

            # For Arris/CommScope E6000: detect CORE (C-CCAP) vs I-CCAP via ifDescr.
            # ifDescr contains 'us-conn' for CORE/C-CCAP (e.g. 'MNDGT0002RPS01-0 us-conn 0') — window only supports rectangular(2).
            # ifDescr does NOT contain 'us-conn' for I-CCAP (e.g. 'cable-upstream 1/scq/0') — supports window 2,3,4,5.
            # IF-MIB::ifDescr OID: 1.3.6.1.2.1.2.2.1.2.<ifindex>
            is_arris_core = False
            if is_arris:
                try:
                    ifdescr_result = await self._snmp_get(f"1.3.6.1.2.1.2.2.1.2.{rf_port_ifindex}")
                    ifdescr_raw = str(ifdescr_result.get('output', ''))
                    ifdescr = ifdescr_raw.split(' = ', 1)[1].strip() if ' = ' in ifdescr_raw else ifdescr_raw.strip()
                    is_arris_core = 'us-conn' in ifdescr.lower()
                    self.logger.info(f"E6000 ifDescr='{ifdescr}' -> {'CORE/C-CCAP (window=rectangular only)' if is_arris_core else 'I-CCAP (window 2-5 supported)'}")
                except Exception as e:
                    self.logger.warning(f"ifDescr lookup failed, assuming CORE (safe): {e}")
                    is_arris_core = True  # safe default: restrict to rectangular

            # Note: bulk destination configuration (docsPnmBulkDataTransferCfgTable and
            # Casa docsPnmCcapBulkDataControlTable) is now handled by the caller via
            # POST /pnm/us/bulk-destination before calling configure.

            # Auto-detect output format if not specified.
            # E6000/Cisco: use fftPower(2) as safe default (docs + field behavior).
            # Casa/EVO: keep fftAmplitude(5) default.
            if output_format is None or output_format == 0:
                if is_arris or is_cisco:
                    self.logger.info("Auto-detecting output format: using fftPower(2) for E6000/Cisco")
                    output_format = 2
                elif is_casa or is_evo:
                    self.logger.info("Auto-detecting output format: using fftAmplitude(5) for Casa/EVO")
                    output_format = 5
                else:
                    self.logger.info("Auto-detecting output format: using safe fallback fftPower(2)")
                    output_format = 2

            # Pre-clamp before first SET to avoid inconsistentValue on strict vendors.
            if is_arris and output_format not in (1, 2, 4):
                self.logger.warning(f"E6000 output_format {output_format} not supported, clamping to 2")
                output_format = 2
            if is_cisco and output_format not in (1, 2, 4):
                self.logger.warning(f"Cisco output_format {output_format} not supported, clamping to 2")
                output_format = 2
            if (is_arris or is_cisco) and 0 < repeat_period_us < 50000 and output_format != 2:
                self.logger.warning(
                    f"repeat_period_us={repeat_period_us} requires fftPower(2) on E6000/Cisco, clamping output_format"
                )
                output_format = 2

            # Keep the caller-requested trigger mode. Some EVO deployments do
            # support freeRunning(2), and forcing idleSid(5) masks valid configs.

            if is_cisco:
                # Cisco cBR-8: rows are NOT pre-provisioned per port.
                # Must destroy existing row then createAndGo to create a fresh active row.
                # Confirmed by test_utsc_cisco.py and operator SNMP scripts.
                target_idx = cfg_index if cfg_index > 0 else 1
                idx = f".{rf_port_ifindex}.{target_idx}"
                self.logger.info(f"Cisco: destroy+createAndGo at cfg_index={target_idx}")
                await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 6, 'i')  # destroy
                await asyncio.sleep(2)
                r = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 4, 'i')  # createAndGo
                self.logger.info(f"Cisco createAndGo result: {r}")
                if not r.get('success'):
                    raise RuntimeError(f"createAndGo failed on {vendor} cfg_index={target_idx}: {r.get('error', r)}")
                await asyncio.sleep(1)
            else:
                # Casa C100G / CommScope EVO vCCAP / Arris E6000:
                # Probe cfg_index rows for a row matching trigger_mode and write in-place.
                # If no row found (e.g. after reboot or first run), fall back to row creation.
                # NOTE: on Casa C100G destroying a row removes the DestinationIndex managed
                # internally — prefer in-place when a row exists.
                # TODO: verify EVO vCCAP restores DestinationIndex after createAndGo (untested)
                # EVO vCCAP: field-validated row index is 3; honor an explicit caller index,
                # otherwise pin EVO to 3 rather than drifting to 1 based on stale rows.
                # Casa C100G / Arris E6000: standard indices 1, 2, 3.
                if is_evo:
                    target_idx = cfg_index if cfg_index > 0 else 3
                    probe_order = [target_idx]
                else:
                    probe_order = [1, 2, 3]
                    target_idx = cfg_index if cfg_index > 0 else probe_order[0]
                row_found = False
                first_existing_idx: Optional[int] = None
                for probe_idx in probe_order:
                    # Probe TriggerMode first (original approach)
                    r = await self._snmp_get(
                        f"{self.OID_UTSC_CFG_TRIGGER_MODE}.{rf_port_ifindex}.{probe_idx}"
                    )
                    v = self._parse_get_value(r)
                    if v is not None and 'No Such' not in str(v):
                        if first_existing_idx is None:
                            first_existing_idx = probe_idx
                        try:
                            if int(v) == trigger_mode:
                                target_idx = probe_idx
                                row_found = True
                                self.logger.info(
                                    f"Found row with TriggerMode={trigger_mode} at cfg_index={probe_idx}"
                                )
                                break
                        except (ValueError, TypeError):
                            pass

                    # EVO row 3 may already exist while TriggerMode is unreadable or stale.
                    if is_evo and not row_found:
                        rs = await self._snmp_get(
                            f"{self.OID_UTSC_CFG_ROW_STATUS}.{rf_port_ifindex}.{probe_idx}"
                        )
                        rs_v = self._parse_get_value(rs)
                        if rs_v is not None and 'No Such' not in str(rs_v):
                            target_idx = probe_idx
                            row_found = True
                            self.logger.info(
                                f"EVO: reusing cfg_index={probe_idx} based on readable RowStatus"
                            )
                            break
                    else:
                        # TriggerMode not readable — check RowStatus as fallback.
                        # Arris E6000 may have an active row where TriggerMode reads
                        # 'No Such Instance' after reboot but RowStatus is still active(1).
                        # WARNING: this RowStatus probe is defense-in-depth added 2026-03-08.
                        # If the rf_port_ifindex is wrong (e.g. logical channel instead of
                        # cable-upstreamRfPort), this probe may mask the real issue by
                        # not finding any rows and falling through to row creation which
                        # will fail with inconsistentValue. The root cause is usually
                        # incorrect ifindex from discovery, not missing rows.
                        rs = await self._snmp_get(
                            f"{self.OID_UTSC_CFG_ROW_STATUS}.{rf_port_ifindex}.{probe_idx}"
                        )
                        rs_v = self._parse_get_value(rs)
                        if rs_v is not None and 'No Such' not in str(rs_v):
                            try:
                                rs_int = int(rs_v)
                                if rs_int in (1, 3):  # active(1) or notReady(3)
                                    if first_existing_idx is None:
                                        first_existing_idx = probe_idx
                                    self.logger.info(
                                        f"RowStatus probe found row at cfg_index={probe_idx} "
                                        f"(status={rs_int}) — TriggerMode was unreadable"
                                    )
                            except (ValueError, TypeError):
                                pass

                # Arris/CommScope often has pre-provisioned fixed rows that reject
                # destroy+createAndGo. If any row exists, reuse it and write columns
                # in-place even when TriggerMode differs.
                if not row_found and first_existing_idx is not None:
                    target_idx = first_existing_idx
                    row_found = True
                    self.logger.info(
                        f"{vendor}: reusing existing cfg_index={target_idx} (trigger mode will be updated in-place)"
                    )

                idx = f".{rf_port_ifindex}.{target_idx}"

                if not row_found:
                    # No pre-provisioned row — create one.
                    # All vendors: destroy + createAndGo(4) — proven flow from provision_utsc.py.
                    create_value = 4
                    create_label = "createAndGo"
                    self.logger.warning(
                        f"{vendor}: no row found for TriggerMode={trigger_mode} "
                        f"— destroy+{create_label} at cfg_index={target_idx}"
                    )
                    await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 6, 'i')  # destroy
                    await asyncio.sleep(2)
                    r = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", create_value, 'i')
                    self.logger.info(f"{vendor} {create_label} result: {r}")
                    if not r.get('success'):
                        # Fallback: try createAndWait(5)
                        self.logger.warning(
                            f"{create_label} failed, trying createAndWait as fallback"
                        )
                        r = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 5, 'i')
                        self.logger.info(f"{vendor} createAndWait fallback result: {r}")
                        if not r.get('success'):
                            raise RuntimeError(
                                f"Row creation failed on {vendor} cfg_index={target_idx}: {r.get('error', r)}"
                            )
                    await asyncio.sleep(1)
                else:
                    self.logger.info(f"Writing columns in-place at cfg_index={target_idx} (no RowStatus touch)...")

                transitioned_not_in_service = False
                if row_found:
                    try:
                        row_status_read = await self._snmp_get(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}")
                        row_status_val = self._parse_get_value(row_status_read)
                        row_status_int = int(row_status_val) if row_status_val and 'No Such' not in str(row_status_val) else None
                    except (ValueError, TypeError):
                        row_status_int = None

                    # vCCAP/Casa can reject TriggerMode updates on active rows.
                    # Put row in notInService(2) before in-place parameter writes.
                    if row_status_int == 1:
                        self.logger.info(f"cfg_index={target_idx} RowStatus=active -> set notInService(2) before configure writes")
                        to_inactive = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 2, 'i')
                        if to_inactive.get('success'):
                            transitioned_not_in_service = True
                            await asyncio.sleep(0.2)
                        else:
                            self.logger.warning(
                                f"Failed to set RowStatus notInService before configure: {to_inactive.get('error')}"
                            )

            # ===== Set parameters (Cisco uses Gauge32/'u' for most values) =====

            # 0. LogicalChIfIndex (.2)
            # UTSC must stay anchored to the physical RF port. Logical channel ifIndex
            # is optional for this flow and should only be set when explicitly provided.
            # Do NOT fallback to RF/0 placeholders here.
            if logical_ch_ifindex is not None:
                logical_result = await self._snmp_set(
                    f"{self.OID_UTSC_CFG_LOGICAL_CH}{idx}", int(logical_ch_ifindex), 'i'
                )
                if not logical_result.get('success'):
                    self.logger.warning(
                        f"LogicalChIfIndex set failed value={logical_ch_ifindex} on {vendor}; "
                        f"continuing without overriding logical channel: {logical_result.get('error')}"
                    )
            else:
                self.logger.info("LogicalChIfIndex not provided for UTSC configure; leaving existing value unchanged")

            # 1. Trigger mode (INTEGER)
            await self._snmp_set(f"{self.OID_UTSC_CFG_TRIGGER_MODE}{idx}", trigger_mode, 'i')
            
            # 2. Center frequency (Gauge32)
            await self._snmp_set(f"{self.OID_UTSC_CFG_CENTER_FREQ}{idx}", center_freq_hz, 'u')
            
            # 3. Span (Gauge32)
            await self._snmp_set(f"{self.OID_UTSC_CFG_SPAN}{idx}", span_hz, 'u')
            
            # 4. Number of bins (Gauge32)
            await self._snmp_set(f"{self.OID_UTSC_CFG_NUM_BINS}{idx}", num_bins, 'u')
            
            # 5. Output format (INTEGER)
            # Casa silently accepts fftAmplitude(5) SET but then rejects row activation.
            # Read back after SET — if it reverted, fall back to fftPower(2).
            await self._snmp_set(f"{self.OID_UTSC_CFG_OUTPUT_FORMAT}{idx}", output_format, 'i')
            await asyncio.sleep(0.1)
            fmt_readback = self._parse_get_value(
                await self._snmp_get(f"{self.OID_UTSC_CFG_OUTPUT_FORMAT}{idx}")
            )
            try:
                if fmt_readback is not None and int(fmt_readback) != output_format:
                    self.logger.warning(
                        f"OutputFormat readback={fmt_readback} != requested={output_format}, using {fmt_readback}"
                    )
                    output_format = int(fmt_readback)
            except (ValueError, TypeError):
                pass
            # clamp_warnings accumulates all vendor constraint adjustments returned to caller
            clamp_warnings = []

            # Casa:          1-6 all accepted (empirically verified 2026-02-23 on mnd-gt0002-ccap101)
            # E6000/Cisco:   timeIQ(1), fftPower(2), fftIQ(4) only for UTSC output format
            if is_cisco and output_format not in (1, 2, 4):
                clamp_warnings.append(f"output_format clamped {output_format} -> 2 (Cisco cBR-8 supports timeIQ(1), fftPower(2), fftIQ(4) only — empirically verified 2026-02-23)")
                output_format = 2
            if is_arris and output_format not in (1, 2, 4):
                clamp_warnings.append(f"output_format clamped {output_format} -> 2 (E6000 supports timeIQ(1), fftPower(2), fftIQ(4) for UTSC)")
                output_format = 2
            if not is_casa and not is_evo and not is_cisco and not is_arris and output_format not in (1, 2, 3, 4, 5):
                output_format = 2  # generic safe fallback
            self.logger.info(f"OutputFormat confirmed={output_format}")
            
            # 6. Window function (INTEGER)
            # Casa:          1-6 all accepted (empirically verified 2026-02-23 on mnd-gt0002-ccap101)
            # E6000 CORE/C-CCAP (ifDescr 'us-conn'): only rectangular(2) supported.
            # E6000 I-CCAP:  2-5 supported (rectangular/hann/blackmanHarris/hamming).
            # Cisco cBR-8:   1-6 all SET accepted; 1 silently maps to 2, 6 silently maps to 5 (empirically verified 2026-02-23).
            if is_arris_core and window_function != 2:
                clamp_warnings.append(f"window_function clamped {window_function} -> 2 (E6000 CORE/C-CCAP only supports rectangular(2))")
                window_function = 2
            elif is_arris and not is_arris_core and window_function not in (2, 3, 4, 5):
                clamp_warnings.append(f"window_function clamped {window_function} -> 2 (E6000 I-CCAP supported: 2-5)")
                window_function = 2
            await self._snmp_set(f"{self.OID_UTSC_CFG_WINDOW}{idx}", window_function, 'i')
            
            # 7. Clamp trigger_count (1-10 on E6000, no limit on Cisco)
            trigger_count = max(trigger_count, 1)

            # ===== Vendor-specific timing constraints =====
            orig_repeat = repeat_period_us
            orig_freerun = freerun_duration_ms

            if is_casa or is_evo:
                # Casa C100G / CommScope EVO vCCAP constraints (from syslog errors):
                #   1. RepeatPeriod >= 100ms
                #   2. FreeRunDuration >= 120s  (is_freerun_trigger_valid)
                #   3. FreeRunDuration / RepeatPeriod <= 300 files
                # Apply in order: floor repeat → floor freerun → raise repeat to satisfy files≤300
                if repeat_period_us < 100000:
                    clamp_warnings.append(f"repeat_period_us clamped {orig_repeat} -> 100000 (Casa minimum 100ms)")
                    repeat_period_us = 100000

                if freerun_duration_ms <= 0:
                    freerun_duration_ms = 120000
                elif freerun_duration_ms < 120000:
                    clamp_warnings.append(f"freerun_duration_ms clamped {orig_freerun} -> 120000 (Casa minimum 120s)")
                    freerun_duration_ms = 120000

                # Casa absolute hard cap: freerun_duration <= 300000ms (5 min)
                # syslog: utsc_freerun_param_check() freerun_duration > 300000 rejected
                CASA_MAX_FREERUN_MS = 300000
                if freerun_duration_ms > CASA_MAX_FREERUN_MS:
                    clamp_warnings.append(f"freerun_duration_ms clamped {freerun_duration_ms} -> {CASA_MAX_FREERUN_MS} (Casa hard max 300s)")
                    freerun_duration_ms = CASA_MAX_FREERUN_MS

                # files = freerun / repeat <= 300  →  repeat >= ceil(freerun / 300)
                min_repeat_us = ((freerun_duration_ms + 299) // 300) * 1000
                if repeat_period_us < min_repeat_us:
                    clamp_warnings.append(f"repeat_period_us raised {repeat_period_us} -> {min_repeat_us} (Casa max 300 files)")
                    repeat_period_us = min_repeat_us
            else:
                # CommScope/Arris E6000 and Cisco cBR-8
                # PDF limits (E6000 Release 13.0 User Guide):
                #   repeat_period: 0=once, 1-49999µs=hw-restricted, 50000-1000000µs=normal, >1000000=rejected
                #   freerun_duration: 1s-600000ms (10min), >600000ms rejected
                #   output_format: if repeat_period 1-49999µs, only fftPower(2) supported
                vendor_label = 'Arris/CommScope E6000' if is_arris else 'Cisco cBR-8' if is_cisco else 'E6000/Cisco'

                # Clamp repeat_period max to 1000ms (PDF: >1000ms rejected)
                max_repeat = 1000000
                if repeat_period_us > max_repeat:
                    clamp_warnings.append(f"repeat_period_us clamped {orig_repeat} -> {max_repeat} ({vendor_label} maximum 1000ms)")
                    repeat_period_us = max_repeat

                # Clamp repeat_period min to 50ms for normal mode
                min_repeat = 50000
                if 0 < repeat_period_us < min_repeat:
                    clamp_warnings.append(f"repeat_period_us clamped {orig_repeat} -> {min_repeat} ({vendor_label} minimum 50ms for normal mode)")
                    repeat_period_us = min_repeat

                # If repeat_period is in hardware-restricted range (1-49999µs), only fftPower(2) allowed
                if 0 < repeat_period_us < 50000 and output_format != 2:
                    clamp_warnings.append(f"output_format clamped {output_format} -> 2 (E6000: repeat_period<50ms requires fftPower(2))")
                    output_format = 2

                # Clamp freerun max to 600000ms (10min) — PDF: >600000ms rejected
                max_freerun = 600000
                if freerun_duration_ms > max_freerun:
                    clamp_warnings.append(f"freerun_duration_ms clamped {freerun_duration_ms} -> {max_freerun} ({vendor_label} maximum 10 minutes)")
                    freerun_duration_ms = max_freerun

                if freerun_duration_ms <= 0:
                    calc_ms = (repeat_period_us // 1000) * trigger_count * 2
                    freerun_duration_ms = max(calc_ms, repeat_period_us // 1000, 60000)

                if freerun_duration_ms < (repeat_period_us // 1000):
                    clamp_warnings.append(f"freerun_duration_ms raised {orig_freerun} -> {repeat_period_us // 1000} (must be >= repeat_period)")
                    freerun_duration_ms = repeat_period_us // 1000

                # E6000: MaxResultsPerFile is read-only fixed at 1 (one TFTP file per capture).
                # Cap freerun so at most 250 files are queued per run. GUI re-triggers when run ends.
                if is_arris:
                    repeat_period_ms = repeat_period_us // 1000 or 1
                    max_freerun_ms = 250 * repeat_period_ms
                    if freerun_duration_ms > max_freerun_ms:
                        clamp_warnings.append(f"freerun_duration_ms clamped {freerun_duration_ms} -> {max_freerun_ms} (E6000 MaxResultsPerFile=1, max 250 files per run)")
                        freerun_duration_ms = max_freerun_ms

                # E6000 num_bins (non-TimeIQ): only 200, 400, 800, 1600, 3200 are valid (PDF Table 6)
                # For TimeIQ: 256, 512, 1024, 2048, 4096 are valid (PDF Table 3)
                if is_arris and output_format != 1:  # non-TimeIQ
                    valid_bins = (200, 400, 800, 1600, 3200)
                    if num_bins not in valid_bins:
                        nearest = min(valid_bins, key=lambda x: abs(x - num_bins))
                        clamp_warnings.append(f"num_bins clamped {num_bins} -> {nearest} (E6000 non-TimeIQ supported values: {valid_bins})")
                        num_bins = nearest

                # Cisco cBR-8: num_bins < 256 silently ignored (stays at previous value) — empirically verified 2026-02-23
                if is_cisco and num_bins < 256:
                    clamp_warnings.append(f"num_bins clamped {num_bins} -> 256 (Cisco cBR-8 minimum 256)")
                    num_bins = 256

                # E6000 CenterFreq: must be multiple of 50 kHz, 0-204 MHz (Wideband) / 0-102 MHz (Narrowband)
                # E6000 returns inconsistentValue on InitiateTest if CenterFreq is out of range.
                if is_arris:
                    if center_freq_hz % 50000 != 0:
                        snapped = round(center_freq_hz / 50000) * 50000
                        clamp_warnings.append(f"center_freq_hz snapped {center_freq_hz} -> {snapped} (E6000: must be multiple of 50 kHz)")
                        center_freq_hz = snapped
                    max_center = 204000000  # Wideband max; Narrowband is 102 MHz but we use Wideband
                    if center_freq_hz > max_center:
                        clamp_warnings.append(f"center_freq_hz clamped {center_freq_hz} -> {max_center} (E6000 Wideband max 204 MHz)")
                        center_freq_hz = max_center

                # E6000 Span: must match supported values per output format (PDF Tables 1-5)
                if is_arris:
                    if output_format == 1:  # TimeIQ — Wideband: 102.4/204.8/409.6 MHz
                        valid_spans = (102400000, 204800000, 409600000)
                    else:  # non-TimeIQ — Wideband: 80/160/320 MHz
                        valid_spans = (80000000, 160000000, 320000000)
                    if span_hz not in valid_spans:
                        nearest = min(valid_spans, key=lambda x: abs(x - span_hz))
                        clamp_warnings.append(f"span_hz snapped {span_hz} -> {nearest} (E6000 supported: {[s // 1000000 for s in valid_spans]} MHz)")
                        span_hz = nearest

            self.logger.info(f"Timing after clamp: repeat={repeat_period_us}µs freerun={freerun_duration_ms}ms num_bins={num_bins} output_format={output_format} warnings={clamp_warnings}")

            # Re-SET values that may have been clamped by vendor rules above
            await self._snmp_set(f"{self.OID_UTSC_CFG_CENTER_FREQ}{idx}", center_freq_hz, 'u')
            await self._snmp_set(f"{self.OID_UTSC_CFG_SPAN}{idx}", span_hz, 'u')
            await self._snmp_set(f"{self.OID_UTSC_CFG_NUM_BINS}{idx}", num_bins, 'u')
            await self._snmp_set(f"{self.OID_UTSC_CFG_OUTPUT_FORMAT}{idx}", output_format, 'i')

            # 9. Set FreeRunDuration FIRST (Gauge32) — must be >= RepeatPeriod
            fr_result = await self._snmp_set(
                f"{self.OID_UTSC_CFG_FREERUN_DUR}{idx}", freerun_duration_ms, 'u'
            )
            self.logger.info(f"FreeRunDuration={freerun_duration_ms}: {fr_result}")
            
            # 10. Set RepeatPeriod (Gauge32)
            rp_result = await self._snmp_set(
                f"{self.OID_UTSC_CFG_REPEAT_PERIOD}{idx}", repeat_period_us, 'u'
            )
            self.logger.info(f"RepeatPeriod={repeat_period_us}: {rp_result}")
            
            # 11. Set TriggerCount (Gauge32)
            await self._snmp_set(
                f"{self.OID_UTSC_CFG_TRIGGER_COUNT}{idx}", trigger_count, 'u'
            )
            self.logger.info(f"TriggerCount={trigger_count}")
            
            # 12. Set filename — E6000 rejects InitiateTest if filename is empty
            # ("Utsc Cfg File name is not specified"). Must be a non-empty string.
            # E6000 appends timestamp: <filename>_YYYY-MM-DD_HH.MM.SS.mmm
            # notWritable on Casa (harmless), not supported on Cisco (harmless).
            await self._snmp_set(
                f"{self.OID_UTSC_CFG_FILENAME}{idx}", filename or "utsc", 's'
            )
            
            # 13. Set destination index if > 0 (Unsigned32)
            if destination_index > 0 and not is_evo:
                await self._snmp_set(
                    f"{self.OID_UTSC_CFG_DEST_INDEX}{idx}", destination_index, 'u'
                )
            
            # 14. For CM MAC trigger mode (mode 7 per Cisco doc, mode 6 per E6000)
            if trigger_mode in (6, 7) and cm_mac_address:
                mac_hex = self.mac_to_hex_string(cm_mac_address)
                await self._snmp_set(
                    f"{self.OID_UTSC_CFG_CM_MAC}{idx}", mac_hex, 'x'
                )
                if logical_ch_ifindex:
                    await self._snmp_set(
                        f"{self.OID_UTSC_CFG_LOGICAL_CH}{idx}", logical_ch_ifindex, 'i'
                    )

            # ===== Verify RowStatus =====
            if transitioned_not_in_service:
                reactivate_result = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 1, 'i')
                if not reactivate_result.get('success'):
                    self.logger.warning(
                        f"Failed to restore RowStatus active after configure: {reactivate_result.get('error')}"
                    )

            await asyncio.sleep(0.3)
            status_result = await self._snmp_get(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}")
            row_status = self._parse_get_value(status_result)
            row_status_names = {1: "active", 2: "notInService", 3: "notReady",
                               4: "createAndGo", 5: "createAndWait", 6: "destroy"}
            if row_status is not None and 'No Such' not in str(row_status):
                row_status_int = int(row_status)
                self.logger.info(f"RowStatus after configure: {row_status_int} "
                                f"({row_status_names.get(row_status_int, 'unknown')})")
                if row_status_int == 3:  # notReady
                    self.logger.warning("RowStatus=notReady — config parameters may be "
                                       "invalid. Check center_freq and span are in valid range.")
            else:
                self.logger.info("RowStatus not readable (normal on some CMTS with SNMP view restrictions)")
            
            # VERIFY critical parameters were accepted
            verify_checks = {
                "trigger_mode": (self.OID_UTSC_CFG_TRIGGER_MODE, trigger_mode),
                "center_freq_hz": (self.OID_UTSC_CFG_CENTER_FREQ, center_freq_hz),
                "span_hz": (self.OID_UTSC_CFG_SPAN, span_hz),
            }
            verify_results = {}
            for param_name, (oid_base, expected) in verify_checks.items():
                try:
                    read_result = await self._snmp_get(f"{oid_base}{idx}")
                    actual = self._parse_get_value(read_result)
                    if actual is not None and 'No Such' not in str(actual):
                        actual_int = int(actual)
                        match = actual_int == expected
                        verify_results[param_name] = {
                            "expected": expected, "actual": actual_int, "match": match
                        }
                        if not match:
                            self.logger.warning(f"VERIFY MISMATCH: {param_name} "
                                              f"expected={expected} actual={actual_int}")
                        else:
                            self.logger.info(f"VERIFY OK: {param_name}={actual_int}")
                    else:
                        self.logger.info(f"VERIFY skip {param_name}: not readable")
                except Exception as ve:
                    self.logger.warning(f"VERIFY failed for {param_name}: {ve}")
            
            return {
                "success": True,
                "message": "UTSC configured",
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": target_idx,
                "warnings": clamp_warnings if clamp_warnings else None,
                "applied": {
                    "repeat_period_us": repeat_period_us,
                    "freerun_duration_ms": freerun_duration_ms,
                },
                "trigger_mode": trigger_mode,
                "filename": filename,
                "row_status": row_status_names.get(int(row_status), 'unknown') if row_status and 'No Such' not in str(row_status) else None,
                "verify": verify_results,
                "error": None
            }
            
        except Exception as e:
            self.logger.error(f"Failed to configure UTSC: {e}")
            return {"success": False, "error": str(e)}
    
    async def start(self, rf_port_ifindex: int, cfg_index: int = 1, trigger_mode: int = 2) -> dict[str, Any]:
        """
        Start UTSC test (set InitiateTest to true).
        
        Note: Auto-clear is handled in configure() to ensure fresh parameters.
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index (0 = auto-probe by TriggerMode)
            trigger_mode: TriggerMode to match when auto-probing (default 2=freeRunning)
            
        Returns:
            Dict with success status
        """
        import asyncio
        requested_cfg_index = cfg_index

        # Probe for the row by TriggerMode — same logic as configure().
        # Casa pre-provisions rows 1-3 with fixed TriggerModes; RowStatus is
        # always createAndWait so probing by RowStatus=active never finds anything.
        # Must match by TriggerMode to find the row configure() actually wrote to.
        resolved = cfg_index if cfg_index > 0 else (3 if is_evo else 1)
        if cfg_index == 0:
            # Auto-probe: find the row matching trigger_mode.
            # For EVO vCCAP: freeRunning(2) is overridden to idleSid(5) in configure(),
            # so also probe for idleSid(5) as a fallback when the caller sends
            # trigger_mode=2 (the GUI default before it knows the applied mode).
            probe_modes = [trigger_mode]
            if trigger_mode == 2:
                probe_modes.append(5)  # idleSid fallback for EVO
            # EVO vCCAP: pin to cfg_index 3 unless caller explicitly overrides.
            start_probe_order = [3] if is_evo else [1, 2, 3]
            match_found = False
            for probe_mode in probe_modes:
                if match_found:
                    break
                for probe_idx in start_probe_order:
                    r = await self._snmp_get(
                        f"{self.OID_UTSC_CFG_TRIGGER_MODE}.{rf_port_ifindex}.{probe_idx}"
                    )
                    v = self._parse_get_value(r)
                    if v is not None and 'No Such' not in str(v):
                        try:
                            if int(v) == probe_mode:
                                resolved = probe_idx
                                self.logger.info(
                                    f"start: found TriggerMode={probe_mode} at cfg_index={probe_idx}"
                                    + (" (EVO idleSid fallback)" if probe_mode != trigger_mode else "")
                                )
                                match_found = True
                                break
                        except (ValueError, TypeError):
                            pass
        self.logger.info(f"Starting UTSC for RF port {rf_port_ifindex}")

        async def _try_start_on_idx(target_idx: int) -> dict[str, Any]:
            idx = f".{rf_port_ifindex}.{target_idx}"

            # If the CMTS already reports BUSY, do not re-trigger InitiateTest.
            # vCCAP logs this as "test already in progress" and may return commitFailed.
            meas_status_result = await self._snmp_get(f"{self.OID_UTSC_STATUS_MEAS}{idx}")
            meas_status_val = self._parse_get_value(meas_status_result)
            try:
                meas_status_int = int(meas_status_val) if meas_status_val and 'No Such' not in str(meas_status_val) else None
            except (ValueError, TypeError):
                meas_status_int = None
            if meas_status_int == 3:
                self.logger.info(f"cfg_index={target_idx} already BUSY; skipping InitiateTest retrigger")
                return {"success": True, "already_running": True}

            # CMTS returns inconsistentValue on InitiateTest if RowStatus != active(1).
            # Always check and set active before triggering (matches provision_utsc.py).
            row_status_result = await self._snmp_get(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}")
            row_status_val = self._parse_get_value(row_status_result)
            try:
                row_status_int = int(row_status_val) if row_status_val and 'No Such' not in str(row_status_val) else None
            except (ValueError, TypeError):
                row_status_int = None

            if row_status_int is None:
                self.logger.warning(f"cfg_index={target_idx} RowStatus unreadable — row may not exist")
                return {"success": False, "error": f"RowStatus unreadable at cfg_index={target_idx}"}

            if row_status_int != 1:
                self.logger.info(f"cfg_index={target_idx} RowStatus={row_status_int} -> set active(1)")
                activate_result = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 1, 'i')
                if not activate_result.get('success'):
                    self.logger.warning(f"RowStatus activate failed: {activate_result.get('error')}")
                    return activate_result
                await asyncio.sleep(1)  # give CMTS time to transition row to active

            # vCCAP reliability: explicitly clear InitiateTest before starting.
            # Some firmware rejects direct 1->1 transitions with commitFailed.
            _ = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 2, 'i')
            await asyncio.sleep(0.2)
            start_result = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 1, 'i')
            if start_result.get('success'):
                return start_result

            # One immediate retry after a second clear for transient CMTS state.
            _ = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 2, 'i')
            await asyncio.sleep(0.2)
            return await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 1, 'i')

        try:
            # If caller explicitly requested a cfg index, do not probe others.
            # Avoid hiding real failures with unrelated "cfg_index=2 unreadable" noise.
            if requested_cfg_index and int(requested_cfg_index) > 0:
                candidate_indices = [resolved]
            else:
                fallback_order = [3] if is_evo else [1, 2, 3]
                candidate_indices = [resolved] + [i for i in fallback_order if i != resolved]
            last_error = None

            for target_idx in candidate_indices:
                result = await _try_start_on_idx(target_idx)
                if result.get('success'):
                    message = "UTSC already running" if result.get('already_running') else "UTSC test started"
                    return {
                        "success": True,
                        "message": message,
                        "rf_port_ifindex": rf_port_ifindex,
                        "cfg_index": target_idx
                    }

                last_error = result.get('error', 'Failed to start UTSC')
                self.logger.warning(f"UTSC start failed on cfg_index={target_idx}: {last_error}")

                # If failure is not row/state related, stop retrying immediately.
                if 'inconsistentValue' not in str(last_error) and 'commitFailed' not in str(last_error):
                    break

            return {"success": False, "error": last_error or 'Failed to start UTSC'}
            
        except Exception as e:
            self.logger.error(f"Failed to start UTSC: {e}")
            return {"success": False, "error": str(e)}
    
    async def stop(self, rf_port_ifindex: int, cfg_index: int = 1) -> dict[str, Any]:
        """
        Stop UTSC test (set InitiateTest to false).
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index
            
        Returns:
            Dict with success status
        """
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        self.logger.info(f"Stopping UTSC for RF port {rf_port_ifindex}")
        
        try:
            # Standard MIB: InitiateTest is TruthValue — use 2 (false) to stop.
            # Arris E6000 rejects 0 (wrongValue). Try 2 first, fallback to 0 for
            # any vendor that maps the field differently.
            result = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 2, 'i')
            if not result.get('success'):
                result = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 0, 'i')
            
            if not result.get('success'):
                return {"success": False, "error": result.get('error', 'Failed to stop UTSC')}
            
            return {
                "success": True,
                "message": "UTSC test stopped",
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
        except Exception as e:
            self.logger.error(f"Failed to stop UTSC: {e}")
            return {"success": False, "error": str(e)}
    
    async def clear_config(self, rf_port_ifindex: int, cfg_index: int = 1) -> dict[str, Any]:
        """
        Clear/reset UTSC configuration by destroying the row.
        
        Sets RowStatus to destroy(6) to remove the configuration entry.
        Use this to force reconfiguration with updated parameters.
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index
            
        Returns:
            Dict with success status
        """
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        self.logger.info(f"Clearing UTSC config for RF port {rf_port_ifindex}, index {cfg_index}")
        
        try:
            # Set RowStatus to destroy(6)
            result = await self._snmp_set(f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 6, 'i')
            
            if not result.get('success'):
                return {"success": False, "error": result.get('error', 'Failed to clear UTSC config')}
            
            return {
                "success": True,
                "message": "UTSC configuration cleared - ready for reconfiguration with new parameters",
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
        except Exception as e:
            self.logger.error(f"Failed to clear UTSC config: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_status(self, rf_port_ifindex: int, cfg_index: int = 1) -> dict[str, Any]:
        """
        Get UTSC test status.
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index
            
        Returns:
            Dict with measurement status
        """
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        try:
            status = {
                "success": True,
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
            # Get measurement status
            result = await self._snmp_get(f"{self.OID_UTSC_STATUS_MEAS}{idx}")
            value = self._parse_get_value(result)
            if value is not None and 'No Such' not in str(value):
                status_value = int(value)
                status_names = {
                    1: "OTHER", 2: "INACTIVE", 3: "BUSY", 4: "SAMPLE_READY",
                    5: "ERROR", 6: "RESOURCE_UNAVAILABLE", 7: "SAMPLE_TRUNCATED"
                }
                status["meas_status"] = status_value
                status["meas_status_name"] = status_names.get(status_value, "UNKNOWN")
                status["is_ready"] = status_value == 4
                status["is_busy"] = status_value == 3
                status["is_error"] = status_value in (5, 6, 7)
            else:
                return {"success": False, "error": result.get('error', 'Failed to get status')}
            
            # Get average power
            try:
                result = await self._snmp_get(f"{self.OID_UTSC_STATUS_AVG_PWR}{idx}")
                value = self._parse_get_value(result)
                if value is not None:
                    # Value is in HundredthsdB
                    status["avg_power"] = int(value) / 100.0
            except Exception:
                pass
            
            # Get filename from config
            try:
                result = await self._snmp_get(f"{self.OID_UTSC_CFG_FILENAME}{idx}")
                value = self._parse_get_value(result)
                if value is not None:
                    status["filename"] = value
            except Exception:
                pass
            
            return status
            
        except Exception as e:
            self.logger.error(f"Failed to get UTSC status: {e}")
            return {"success": False, "error": str(e)}
