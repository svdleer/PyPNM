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
    
    # Bulk Data Transfer (BDT) Control - required by Cisco cBR-8
    OID_BDT_CONTROL = "1.3.6.1.4.1.4491.2.1.27.1.1.1"
    OID_BDT_IP_ADDR_TYPE = f"{OID_BDT_CONTROL}.1.0"            # InetAddressType (1=IPv4, 2=IPv6)
    OID_BDT_IP_ADDR = f"{OID_BDT_CONTROL}.2.0"                 # InetAddress (hex IP)
    OID_BDT_PATH = f"{OID_BDT_CONTROL}.3.0"                    # Destination path
    
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
    
    @staticmethod
    def mac_to_hex_string(mac_address: str) -> str:
        """Convert MAC address to hex string for agent SNMP SET (type='x')."""
        return mac_address.lower().replace(":", "").replace("-", "").replace(".", "")
    
    # ============================================
    # UTSC Operations
    # ============================================
    
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
                for entry in result['results']:
                    oid_str = str(entry.get('oid', ''))
                    
                    # Extract RF port ifIndex and cfg index from OID suffix
                    # Format: ...3.{rfPortIfIndex}.{cfgIndex}
                    suffix = oid_str.split(self.OID_UTSC_CFG_TRIGGER_MODE + ".")[-1]
                    parts = suffix.split(".")
                    if len(parts) >= 2:
                        rf_port_ifindex = int(parts[0])
                        cfg_index = int(parts[1])
                        
                        # Get port description
                        description = None
                        try:
                            desc_result = await self._snmp_get(f"{self.OID_IF_DESCR}.{rf_port_ifindex}")
                            desc_value = self._parse_get_value(desc_result)
                            if desc_value:
                                description = desc_value
                        except Exception:
                            pass
                        
                        rf_ports.append({
                            "rf_port_ifindex": rf_port_ifindex,
                            "cfg_index": cfg_index,
                            "description": description
                        })
            
            if rf_ports:
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
                re.compile(r'Cable\d+/\d+/US\d+', re.I),                    # Cisco cBR-8
                re.compile(r'Integrated-Cable\d+/\d+/US\d+', re.I),         # Cisco cBR-8 integrated
                re.compile(r'Upstream-Cable\d+', re.I),                      # Cisco legacy
                re.compile(r'us-conn\s+\d+/\d+', re.I),                      # CommScope E6000
                re.compile(r'cable-upstream\s+\d+/\d+\.\d+', re.I),         # Casa / Generic
                re.compile(r'upstream\d+', re.I),                            # Generic
            ]
            
            for entry in descr_result['results']:
                oid_str = str(entry.get('oid', ''))
                descr = str(entry.get('value', ''))
                
                if not descr or 'No Such' in descr:
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
                # Cisco logical channels have very high ifIndexes (>840M)
                # and descriptions like "Cable8/0/0-upstream3"
                if ifindex >= 840000000:
                    continue
                
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
    
    async def configure_bdt(
        self,
        tftp_server_ip: str,
        tftp_path: str = "pnm"
    ) -> dict[str, Any]:
        """
        Configure Bulk Data Transfer (BDT) for PNM file transfer.
        
        Required by Cisco cBR-8 before UTSC captures — the guestshell IOX
        container uses BDT to TFTP capture files to a destination server.
        CommScope E6000 also uses BDT for remote file transfer.
        
        Args:
            tftp_server_ip: TFTP server IPv4 address (e.g. "10.1.2.3")
            tftp_path: Destination path on TFTP server (e.g. "pnm")
            
        Returns:
            Dict with success status
        """
        self.logger.info(f"Configuring BDT: TFTP server={tftp_server_ip}, path={tftp_path}")
        
        try:
            # Convert IP address to hex bytes: "10.1.2.3" -> "0A010203"
            import ipaddress
            ip_bytes = ipaddress.IPv4Address(tftp_server_ip).packed
            ip_hex = ip_bytes.hex()
            
            # Set IP address (hex OctetString)
            result = await self._snmp_set(self.OID_BDT_IP_ADDR, ip_hex, 'x')
            if not result.get('success'):
                return {"success": False, "error": f"Failed to set BDT IP: {result.get('error')}"}
            
            # Set destination path (string)
            result = await self._snmp_set(self.OID_BDT_PATH, tftp_path, 's')
            if not result.get('success'):
                self.logger.warning(f"BDT path set failed (may not be required): {result.get('error')}")
            
            self.logger.info(f"BDT configured: {tftp_server_ip} -> {tftp_path}")
            return {
                "success": True,
                "message": f"BDT configured: TFTP {tftp_server_ip}/{tftp_path}",
                "tftp_server": tftp_server_ip,
                "tftp_path": tftp_path
            }
            
        except Exception as e:
            self.logger.error(f"Failed to configure BDT: {e}")
            return {"success": False, "error": str(e)}
    
    async def configure(
        self,
        rf_port_ifindex: int,
        cfg_index: int = 1,
        trigger_mode: int = 2,
        cm_mac_address: Optional[str] = None,
        logical_ch_ifindex: Optional[int] = None,
        center_freq_hz: int = 30000000,
        span_hz: int = 80000000,
        num_bins: int = 800,
        output_format: int = 2,
        window_function: int = 2,
        repeat_period_us: int = 50000,
        freerun_duration_ms: int = 0,  # 0 = auto-calculate
        trigger_count: int = 10,
        filename: str = "utsc_capture",
        destination_index: int = 1,
        auto_clear: bool = True
    ) -> dict[str, Any]:
        """
        Configure UTSC test parameters.
        
        Supports both CommScope E6000 and Cisco cBR-8 CMTS:
        
        **Cisco cBR-8 workflow** (per Cisco PNM documentation):
        1. Configure BDT (TFTP server) — call configure_bdt() first
        2. createAndGo(4) to create config entry
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
            output_format: 2=fftPower (Cisco), 5=fftAmplitude (E6000)
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
            
            # Check if UTSC config row exists by reading trigger mode
            check_result = await self._snmp_get(f"{self.OID_UTSC_CFG_TRIGGER_MODE}{idx}")
            check_value = self._parse_get_value(check_result)
            row_exists = (check_result.get('success', False) 
                         and check_value is not None
                         and 'No Such' not in str(check_value))
            
            if row_exists:
                # Row exists (CommScope E6000 pre-creates rows, Cisco cBR-8
                # also pre-creates rows for each us-conn port).
                # Stop any running test so parameters can be modified in-place.
                self.logger.info("UTSC row exists — stopping any running test...")
                stop_result = await self.stop(rf_port_ifindex, cfg_index)
                self.logger.info(f"Stop result: {stop_result}")
                await asyncio.sleep(0.5)
                # Note: Do NOT destroy+recreate — Cisco cBR-8 pre-creates rows
                # and will reject createAndGo after destroy. Just modify in-place.
            
            if not row_exists:
                # Create config entry with RowStatus = createAndGo(4)
                # Per Cisco doc: "All capture entries must first be created
                # by a client on a port before attempting to initiate any tests"
                self.logger.info("Creating UTSC config entry with createAndGo(4)...")
                create_result = await self._snmp_set(
                    f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 4, 'i'  # 4 = createAndGo
                )
                if not create_result.get('success'):
                    # Fallback: createAndWait(5)
                    self.logger.warning(f"createAndGo failed: {create_result.get('error')}, "
                                       f"trying createAndWait(5)")
                    create_result = await self._snmp_set(
                        f"{self.OID_UTSC_CFG_ROW_STATUS}{idx}", 5, 'i'
                    )
                    if not create_result.get('success'):
                        return {"success": False, 
                                "error": f"Cannot create UTSC config row: {create_result.get('error')}"}
                await asyncio.sleep(0.5)
                self.logger.info("UTSC config entry created")
            
            # ===== Set parameters (Cisco uses Gauge32/'u' for most values) =====
            
            # 1. Trigger mode (INTEGER)
            await self._snmp_set(f"{self.OID_UTSC_CFG_TRIGGER_MODE}{idx}", trigger_mode, 'i')
            
            # 2. Center frequency (Gauge32)
            await self._snmp_set(f"{self.OID_UTSC_CFG_CENTER_FREQ}{idx}", center_freq_hz, 'u')
            
            # 3. Span (Gauge32)
            await self._snmp_set(f"{self.OID_UTSC_CFG_SPAN}{idx}", span_hz, 'u')
            
            # 4. Number of bins (Gauge32)
            await self._snmp_set(f"{self.OID_UTSC_CFG_NUM_BINS}{idx}", num_bins, 'u')
            
            # 5. Output format (INTEGER) — Cisco: only 1 or 2
            await self._snmp_set(f"{self.OID_UTSC_CFG_OUTPUT_FORMAT}{idx}", output_format, 'i')
            
            # 6. Window function (INTEGER)
            await self._snmp_set(f"{self.OID_UTSC_CFG_WINDOW}{idx}", window_function, 'i')
            
            # 7. Clamp trigger_count (1-10 on E6000, no limit on Cisco)
            trigger_count = max(trigger_count, 1)
            
            # 8. Auto-calculate FreeRunDuration if not explicitly set
            if freerun_duration_ms <= 0:
                # Default: use RepeatPeriod raw value for E6000 compat, or
                # a sensible default (5000ms = 5 seconds) for Cisco
                freerun_duration_ms = max(repeat_period_us, 5000)
                self.logger.info(f"Auto-set FreeRunDuration={freerun_duration_ms}")
            
            # Cisco constraint: RepeatPeriod must not exceed FreeRunDuration
            # E6000 constraint: FreeRunDuration raw >= RepeatPeriod raw
            if freerun_duration_ms < repeat_period_us:
                freerun_duration_ms = repeat_period_us
                self.logger.warning(f"FreeRunDuration clamped to {freerun_duration_ms} "
                                   f"(>= RepeatPeriod)")
            
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
            
            # 12. Set filename (OctetString) — NOT supported on Cisco cBR-8
            fn_result = await self._snmp_set(
                f"{self.OID_UTSC_CFG_FILENAME}{idx}", filename, 's'
            )
            if not fn_result.get('success'):
                self.logger.info(f"Filename SET skipped (unsupported on Cisco): {fn_result.get('error', '')}")
            
            # 13. Set destination index if > 0 (Unsigned32)
            if destination_index > 0:
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
            
            # ===== Verify RowStatus is Active =====
            await asyncio.sleep(0.5)
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
                "cfg_index": cfg_index,
                "trigger_mode": trigger_mode,
                "filename": filename,
                "row_status": row_status_names.get(int(row_status), 'unknown') if row_status and 'No Such' not in str(row_status) else None,
                "verify": verify_results,
                "error": None
            }
            
        except Exception as e:
            self.logger.error(f"Failed to configure UTSC: {e}")
            return {"success": False, "error": str(e)}
    
    async def start(self, rf_port_ifindex: int, cfg_index: int = 1) -> dict[str, Any]:
        """
        Start UTSC test (set InitiateTest to true).
        
        Note: Auto-clear is handled in configure() to ensure fresh parameters.
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index
            
        Returns:
            Dict with success status
        """
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        self.logger.info(f"Starting UTSC for RF port {rf_port_ifindex}")
        
        try:
            # Set InitiateTest to true (1)
            result = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 1, 'i')
            
            if not result.get('success'):
                return {"success": False, "error": result.get('error', 'Failed to start UTSC')}
            
            return {
                "success": True,
                "message": "UTSC test started",
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
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
            # Set InitiateTest to false
            # Cisco uses 0 to stop, standard MIB uses 2 (TruthValue false)
            # Try 0 first (Cisco), fallback to 2
            result = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 0, 'i')
            if not result.get('success'):
                result = await self._snmp_set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 2, 'i')
            
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
