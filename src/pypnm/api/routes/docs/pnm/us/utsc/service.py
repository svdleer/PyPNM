# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Service for CMTS Upstream Triggered Spectrum Capture (UTSC) operations.

This module provides async methods for CMTS-side UTSC measurements
using pysnmp for direct CMTS SNMP communication.

OIDs used (from DOCS-PNM-MIB):
- docsPnmCmtsUtscCfgTable: 1.3.6.1.4.1.4491.2.1.27.1.3.10.2
- docsPnmCmtsUtscCtrlTable: 1.3.6.1.4.1.4491.2.1.27.1.3.10.3
- docsPnmCmtsUtscStatusTable: 1.3.6.1.4.1.4491.2.1.27.1.3.10.4
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any, Optional

from pysnmp.proto.rfc1902 import Gauge32, Integer32, OctetString

from pypnm.snmp.snmp_v2c import Snmp_v2c
from pypnm.lib.inet import Inet


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
    """UTSC Output Format"""
    TIME_IQ = 1
    FFT_POWER = 2
    FFT_IQ = 3
    FFT_AMPLITUDE = 4
    FFT_POWER_AND_PHASE = 5
    RAW_ADC = 6


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
    OID_UTSC_CFG_DEST_INDEX = f"{OID_UTSC_CFG_TABLE}.23"      # DestinationIndex
    OID_UTSC_CFG_NUM_AVGS = f"{OID_UTSC_CFG_TABLE}.24"        # NumAvgs
    
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
    
    async def list_rf_ports(self) -> dict[str, Any]:
        """
        List available RF ports for UTSC.
        
        Scans the UTSC config table to find available RF port indexes.
        
        Returns:
            Dict with list of RF ports and their configurations
        """
        snmp = self._get_snmp()
        rf_ports = []
        
        try:
            # Walk the trigger mode to find configured RF ports
            results = await snmp.bulk_walk(self.OID_UTSC_CFG_TRIGGER_MODE, max_repetitions=50)
            
            if not results:
                return {"success": True, "rf_ports": []}
            
            for var_bind in results:
                oid_str = str(var_bind[0])
                
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
                        desc_result = await snmp.get(f"{self.OID_IF_DESCR}.{rf_port_ifindex}")
                        if desc_result:
                            description = str(desc_result[0][1])
                    except Exception:
                        pass
                    
                    rf_ports.append({
                        "rf_port_ifindex": rf_port_ifindex,
                        "cfg_index": cfg_index,
                        "description": description
                    })
            
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
        snmp = self._get_snmp()
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
                    result = await snmp.get(f"{oid_base}{idx}")
                    if result:
                        value = result[0][1]
                        if converter == str:
                            config[key] = str(value)
                        else:
                            config[key] = int(value)
                except Exception:
                    pass
            
            # Add human-readable names
            if "trigger_mode" in config:
                trigger_names = {1: "other", 2: "freeRunning", 3: "minislotCount", 
                                4: "sid", 5: "iuc", 6: "cmMac"}
                config["trigger_mode_name"] = trigger_names.get(config["trigger_mode"], "unknown")
            
            if "output_format" in config:
                output_names = {1: "timeIq", 2: "fftPower", 3: "fftIq", 
                               4: "fftAmplitude", 5: "fftPowerAndPhase", 6: "rawAdc"}
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
        output_format: int = 2,
        window_function: int = 2,
        repeat_period_us: int = 1000000,
        freerun_duration_ms: int = 60000,
        trigger_count: int = 1,
        filename: str = "utsc_capture",
        destination_index: int = 0
    ) -> dict[str, Any]:
        """
        Configure UTSC test parameters.
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index
            trigger_mode: 1=other, 2=freeRunning, 3=minislotCount, 4=sid, 5=iuc, 6=cmMac
            cm_mac_address: CM MAC address (required for trigger_mode=6)
            logical_ch_ifindex: Logical channel ifIndex for CM MAC trigger
            center_freq_hz: Center frequency in Hz
            span_hz: Frequency span in Hz
            num_bins: Number of FFT bins
            output_format: 1=timeIq, 2=fftPower, etc.
            window_function: Window function for FFT
            repeat_period_us: Repeat period in microseconds
            freerun_duration_ms: Free run duration in milliseconds
            trigger_count: Number of captures
            filename: Output filename
            destination_index: Bulk transfer destination (0=local only)
            
        Returns:
            Dict with success status
        """
        snmp = self._get_snmp()
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        self.logger.info(f"Configuring UTSC for RF port {rf_port_ifindex}, trigger_mode={trigger_mode}")
        
        try:
            # 1. Set trigger mode
            await snmp.set(f"{self.OID_UTSC_CFG_TRIGGER_MODE}{idx}", trigger_mode, Integer32)
            
            # 2. Set center frequency
            await snmp.set(f"{self.OID_UTSC_CFG_CENTER_FREQ}{idx}", center_freq_hz, Gauge32)
            
            # 3. Set span
            await snmp.set(f"{self.OID_UTSC_CFG_SPAN}{idx}", span_hz, Gauge32)
            
            # 4. Set number of bins
            await snmp.set(f"{self.OID_UTSC_CFG_NUM_BINS}{idx}", num_bins, Gauge32)
            
            # 5. Set output format
            await snmp.set(f"{self.OID_UTSC_CFG_OUTPUT_FORMAT}{idx}", output_format, Integer32)
            
            # 6. Set window function
            await snmp.set(f"{self.OID_UTSC_CFG_WINDOW}{idx}", window_function, Integer32)
            
            # 7. Set repeat period (microseconds)
            await snmp.set(f"{self.OID_UTSC_CFG_REPEAT_PERIOD}{idx}", repeat_period_us, Gauge32)
            
            # 8. Set free run duration (milliseconds)
            await snmp.set(f"{self.OID_UTSC_CFG_FREERUN_DUR}{idx}", freerun_duration_ms, Gauge32)
            
            # 9. Set trigger count
            await snmp.set(f"{self.OID_UTSC_CFG_TRIGGER_COUNT}{idx}", trigger_count, Gauge32)
            
            # 10. Set filename
            await snmp.set(f"{self.OID_UTSC_CFG_FILENAME}{idx}", filename, OctetString)
            
            # 11. Set destination index if > 0
            if destination_index > 0:
                await snmp.set(f"{self.OID_UTSC_CFG_DEST_INDEX}{idx}", destination_index, Gauge32)
            
            # 12. For CM MAC trigger mode
            if trigger_mode == 6 and cm_mac_address:
                mac_octets = self.mac_to_hex_octets(cm_mac_address)
                await snmp.set(f"{self.OID_UTSC_CFG_CM_MAC}{idx}", mac_octets, OctetString)
                
                if logical_ch_ifindex:
                    await snmp.set(f"{self.OID_UTSC_CFG_LOGICAL_CH}{idx}", logical_ch_ifindex, Integer32)
            
            return {
                "success": True,
                "message": "UTSC configured",
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index,
                "trigger_mode": trigger_mode,
                "filename": filename
            }
            
        except Exception as e:
            self.logger.error(f"Failed to configure UTSC: {e}")
            return {"success": False, "error": str(e)}
    
    async def start(self, rf_port_ifindex: int, cfg_index: int = 1) -> dict[str, Any]:
        """
        Start UTSC test (set InitiateTest to true).
        
        Args:
            rf_port_ifindex: RF port ifIndex
            cfg_index: Config table index
            
        Returns:
            Dict with success status
        """
        snmp = self._get_snmp()
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        self.logger.info(f"Starting UTSC for RF port {rf_port_ifindex}")
        
        try:
            # Set InitiateTest to true (1)
            await snmp.set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 1, Integer32)
            
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
        snmp = self._get_snmp()
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        self.logger.info(f"Stopping UTSC for RF port {rf_port_ifindex}")
        
        try:
            # Set InitiateTest to false (2)
            await snmp.set(f"{self.OID_UTSC_CTRL_INITIATE}{idx}", 2, Integer32)
            
            return {
                "success": True,
                "message": "UTSC test stopped",
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
        except Exception as e:
            self.logger.error(f"Failed to stop UTSC: {e}")
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
        snmp = self._get_snmp()
        idx = f".{rf_port_ifindex}.{cfg_index}"
        
        try:
            status = {
                "success": True,
                "rf_port_ifindex": rf_port_ifindex,
                "cfg_index": cfg_index
            }
            
            # Get measurement status
            result = await snmp.get(f"{self.OID_UTSC_STATUS_MEAS}{idx}")
            if result:
                status_value = int(result[0][1])
                status_names = {
                    1: "OTHER", 2: "INACTIVE", 3: "BUSY", 4: "SAMPLE_READY",
                    5: "ERROR", 6: "RESOURCE_UNAVAILABLE", 7: "SAMPLE_TRUNCATED"
                }
                status["meas_status"] = status_value
                status["meas_status_name"] = status_names.get(status_value, "UNKNOWN")
                status["is_ready"] = status_value == 4
                status["is_busy"] = status_value == 3
                status["is_error"] = status_value in (5, 6, 7)
            
            # Get average power
            try:
                result = await snmp.get(f"{self.OID_UTSC_STATUS_AVG_PWR}{idx}")
                if result:
                    # Value is in HundredthsdB
                    status["avg_power"] = int(result[0][1]) / 100.0
            except Exception:
                pass
            
            # Get filename from config
            try:
                result = await snmp.get(f"{self.OID_UTSC_CFG_FILENAME}{idx}")
                if result:
                    status["filename"] = str(result[0][1])
            except Exception:
                pass
            
            return status
            
        except Exception as e:
            self.logger.error(f"Failed to get UTSC status: {e}")
            return {"success": False, "error": str(e)}
