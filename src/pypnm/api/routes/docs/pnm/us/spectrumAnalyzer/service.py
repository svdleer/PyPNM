# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration
# Based on DOCSIS UTSC (Upstream Triggered Spectrum Capture)

from __future__ import annotations

import asyncio
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
        self.snmp = Snmp_v2c(cmts_ip, read_community=community, write_community=community, timeout=3, retries=1)
        self.cfg_idx = 1  # Use index .1 which exists on this CMTS
    
    async def _safe_snmp_set(self, oid: str, value, value_type, description: str = "") -> bool:
        """Safe SNMP SET with timeout and error handling"""
        try:
            self.logger.debug(f"SNMP SET: {description} - OID={oid}")
            result = await asyncio.wait_for(
                self.snmp.set(oid, value, value_type),
                timeout=5.0  # 5 second timeout per operation
            )
            if result:
                self.logger.debug(f"SNMP SET SUCCESS: {description}")
                return True
            else:
                self.logger.warning(f"SNMP SET returned None: {description} - OID={oid}")
                return False
        except asyncio.TimeoutError:
            self.logger.error(f"SNMP SET TIMEOUT: {description} - OID={oid}")
            return False
        except Exception as e:
            self.logger.error(f"SNMP SET ERROR: {description} - OID={oid} - {str(e)}")
            return False
    
    async def _safe_snmp_get(self, oid: str, description: str = ""):
        """Safe SNMP GET with timeout and error handling"""
        try:
            self.logger.debug(f"SNMP GET: {description} - OID={oid}")
            result = await asyncio.wait_for(
                self.snmp.get(oid),
                timeout=5.0
            )
            return result
        except asyncio.TimeoutError:
            self.logger.error(f"SNMP GET TIMEOUT: {description} - OID={oid}")
            return None
        except Exception as e:
            self.logger.debug(f"SNMP GET ERROR: {description} - OID={oid} - {str(e)}")
            return None
    
    async def _check_row_exists(self, idx: str) -> bool:
        """Check if UTSC configuration row already exists"""
        oid = f"{self.UTSC_CFG_BASE}.21{idx}"  # docsPnmCmtsUtscCfgStatus (RowStatus is field .21)
        result = await self._safe_snmp_get(oid, f"Check row exists for {idx}")
        return result is not None and len(result) > 0
    
    async def reset_port_state(self) -> dict:
        """Reset UTSC port to a clean state before configuring.
        
        This ensures the port is not in an inconsistent state from previous
        failed operations. Steps:
        1. Stop any active capture (InitiateTest = false/2)
        2. Wait for status to become inactive/sampleReady (not busy)
        3. Verify row is in active state
        
        Returns:
            dict: {"success": True/False, "status": status_value, "error": error_msg}
        """
        try:
            self.logger.info(f"Resetting UTSC port state for RF Port {self.rf_port_ifindex}")
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            
            # Step 1: Stop any active capture
            stop_oid = f"{self.UTSC_CTRL_BASE}.1{idx}"  # docsPnmCmtsUtscCtrlInitiateTest
            self.logger.info("Stopping any active UTSC capture...")
            await self._safe_snmp_set(stop_oid, 2, Integer32, "Stop UTSC (InitiateTest=false)")
            
            # Step 2: Wait for status to become not-busy (with timeout)
            status_oid = f"{self.UTSC_STATUS_BASE}.1{idx}"  # docsPnmCmtsUtscStatusMeasStatus
            max_wait_time = 10  # seconds
            poll_interval = 0.5
            waited = 0
            
            while waited < max_wait_time:
                result = await self._safe_snmp_get(status_oid, "Check MeasStatus")
                if result:
                    try:
                        # Extract status value
                        status_value = int(result[0][1])
                        self.logger.debug(f"UTSC MeasStatus = {status_value}")
                        
                        # Status values: 1=other, 2=inactive, 3=busy, 4=sampleReady, 5=error
                        if status_value != 3:  # Not busy
                            self.logger.info(f"Port is ready (status={status_value})")
                            break
                    except (IndexError, ValueError, TypeError):
                        pass
                
                await asyncio.sleep(poll_interval)
                waited += poll_interval
            
            if waited >= max_wait_time:
                self.logger.warning(f"Timeout waiting for port to become ready (waited {max_wait_time}s)")
            
            # Step 3: Verify RowStatus is active
            row_status_oid = f"{self.UTSC_CFG_BASE}.21{idx}"  # docsPnmCmtsUtscCfgStatus
            result = await self._safe_snmp_get(row_status_oid, "Check RowStatus")
            row_status = None
            if result:
                try:
                    row_status = int(result[0][1])
                    self.logger.info(f"Row status = {row_status} (1=active, 2=notInService)")
                except (IndexError, ValueError, TypeError):
                    pass
            
            # Get final status for return
            final_status = None
            result = await self._safe_snmp_get(status_oid, "Get final MeasStatus")
            if result:
                try:
                    final_status = int(result[0][1])
                except (IndexError, ValueError, TypeError):
                    pass
            
            self.logger.info(f"Port state reset complete. Status={final_status}, RowStatus={row_status}")
            return {
                "success": True, 
                "status": final_status,
                "row_status": row_status
            }
            
        except Exception as e:
            error_msg = f"Failed to reset port state: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    async def configure(
        self, 
        center_freq_hz: int, 
        span_hz: int, 
        num_bins: int, 
        trigger_mode: int, 
        filename: str,
        tftp_ip: str,
        cm_mac: str | None = None,
        logical_ch_ifindex: int | None = None,
        repeat_period_ms: int = 100,
        freerun_duration_ms: int = 60000,
        trigger_count: int = 1,
        output_format: int = 5,  # 5 = fftAmplitude (better for visualization)
        window: int = 2
    ) -> dict:
        """Configure UTSC per E6000 CER I-CCAP User Guide Release 13.0.
        
        OID field mapping (docsPnmCmtsUtscCfgEntry):
        .2  = LogicalChIfIndex
        .3  = TriggerMode (2=FreeRunning, 5=IdleSID, 6=cmMAC)
        .6  = CmMacAddr
        .8  = CenterFreq (Hz)
        .9  = Span (Hz)
        .10 = NumBins (200,400,800,1600,3200 or 256,512,1024,2048)
        .12 = Filename
        .16 = Window (2=rectangular, 3=hann, 4=blackmanHarris, 5=hamming)
        .17 = OutputFormat (1=timeIQ, 2=fftPower, 4=fftIQ, 5=fftAmplitude)
        .18 = RepeatPeriod (microseconds, 0-1000000)
        .19 = FreeRunDuration (milliseconds, 1000-600000)
        .20 = TriggerCount (1-10)
        .24 = DestinationIndex (1 = pre-configured TFTP)
        """
        try:
            self.logger.info(f"Starting UTSC configuration for CMTS={self.cmts_ip}, RF Port={self.rf_port_ifindex}")
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            
            # Convert ms to microseconds for RepeatPeriod
            repeat_period_us = repeat_period_ms * 1000
            
            # 1. Set trigger mode
            self.logger.info(f"Setting TriggerMode={trigger_mode}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.3{idx}", trigger_mode, Integer32, f"Trigger Mode ({trigger_mode})")
            
            # 2. Set capture parameters
            self.logger.info(f"Setting NumBins={num_bins}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.10{idx}", num_bins, Unsigned32, f"Num Bins ({num_bins})")
            
            self.logger.info(f"Setting CenterFreq={center_freq_hz} Hz")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.8{idx}", center_freq_hz, Unsigned32, f"Center Freq ({center_freq_hz} Hz)")
            
            self.logger.info(f"Setting Span={span_hz} Hz")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.9{idx}", span_hz, Unsigned32, f"Span ({span_hz} Hz)")
            
            # 3. Set output format and window
            self.logger.info(f"Setting OutputFormat={output_format}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.17{idx}", output_format, Integer32, f"Output Format ({output_format})")
            
            self.logger.info(f"Setting Window={window}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.16{idx}", window, Integer32, f"Window ({window})")
            
            # 4. Set filename
            self.logger.info(f"Setting Filename={filename}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.12{idx}", filename, OctetString, f"Filename ({filename})")
            
            # 5. Set timing parameters for FreeRunning mode
            if trigger_mode == 2:
                # RepeatPeriod: E6000 minimum is 50ms (50000 µs), granularity 50ms
                repeat_period_us_validated = max(50000, repeat_period_us)
                if repeat_period_us_validated != repeat_period_us:
                    self.logger.warning(f"RepeatPeriod {repeat_period_us}µs is below E6000 minimum 50ms, using 50000µs")
                
                self.logger.info(f"Setting RepeatPeriod={repeat_period_us_validated}µs ({repeat_period_us_validated/1000}ms)")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.18{idx}", repeat_period_us_validated, Unsigned32, f"Repeat Period ({repeat_period_us_validated} us)")
                
                self.logger.info(f"Setting FreeRunDuration={freerun_duration_ms}ms")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.19{idx}", freerun_duration_ms, Unsigned32, f"FreeRun Duration ({freerun_duration_ms}ms)")
            
            # 6. Set TriggerCount (ONLY for IdleSID/cmMAC trigger modes, NOT for FreeRunning)
            if trigger_mode in (5, 6):
                self.logger.info(f"Setting TriggerCount={trigger_count} (trigger mode {trigger_mode})")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.20{idx}", trigger_count, Unsigned32, f"Trigger Count ({trigger_count})")
            elif trigger_mode == 2:
                self.logger.info("Skipping TriggerCount for FreeRunning mode (parameter ignored by CMTS)")
            
            # 7. Set DestinationIndex = 1 (use pre-configured TFTP destination)
            self.logger.info("Setting DestinationIndex=1 (pre-configured TFTP)")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.24{idx}", 1, Unsigned32, "Destination Index (1)")
            
            # 8. For CM MAC trigger mode (mode 6) or IdleSID (mode 5), set CM info
            if trigger_mode in (5, 6) and cm_mac:
                self.logger.info(f"Setting CM MAC={cm_mac}")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.6{idx}", cm_mac, OctetString, f"CM MAC ({cm_mac})")
                if logical_ch_ifindex:
                    await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.2{idx}", logical_ch_ifindex, Integer32, f"Logical Ch ifIndex ({logical_ch_ifindex})")
            
            self.logger.info("UTSC configuration completed successfully")
            return {"success": True, "cmts_ip": str(self.cmts_ip)}
            
        except asyncio.TimeoutError:
            error_msg = "UTSC configuration timed out"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"UTSC configuration failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    async def start(self) -> dict:
        """Start UTSC capture with error handling"""
        try:
            self.logger.info(f"Starting UTSC capture for RF Port {self.rf_port_ifindex}")
            # OID structure: docsPnmCmtsUtscCtrlTable.docsPnmCmtsUtscCtrlEntry.Column.{rfPort}.{cfgIdx}
            # UTSC_CTRL_BASE = 1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1 (docsPnmCmtsUtscCtrlEntry)
            # Column 1 = docsPnmCmtsUtscCtrlInitiateTest
            # Full OID: {UTSC_CTRL_BASE}.1.{rfPort}.{cfgIdx} = 1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{rf}.{idx}
            oid = f"{self.UTSC_CTRL_BASE}.1.{self.rf_port_ifindex}.{self.cfg_idx}"
            
            if not await self._safe_snmp_set(oid, 1, Integer32, "Initiate UTSC Test"):
                return {"success": False, "error": "Failed to initiate UTSC capture"}
            
            self.logger.info("UTSC capture initiated successfully")
            return {"success": True}
        except Exception as e:
            error_msg = f"Failed to start UTSC: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}


class UtscRfPortDiscoveryService:
    """Service to discover the correct RF port for a modem's upstream channel.
    
    Uses the modem's upstream logical channel to find which UTSC RF port it belongs to.
    """
    
    # docsIf3CmtsCmRegStatusMacAddr
    CM_REG_STATUS_MAC = "1.3.6.1.4.1.4491.2.1.20.1.3.1.2"
    # docsIf3CmtsCmUsStatusRxPower (to find US channels by CM index)
    CM_US_STATUS_RXPOWER = "1.3.6.1.4.1.4491.2.1.20.1.4.1.2"
    # docsPnmCmtsUtscCfgLogicalChIfIndex (to get RF ports)
    UTSC_CFG_LOGICAL_CH = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2"
    
    def __init__(self, cmts_ip: Inet, community: str = "private") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cmts_ip = cmts_ip
        self.snmp = Snmp_v2c(cmts_ip, read_community=community, write_community=community, timeout=3, retries=1)
    
    async def _safe_walk(self, oid: str, description: str = "") -> list:
        """Safe SNMP WALK with timeout"""
        try:
            self.logger.debug(f"SNMP WALK: {description} - OID={oid}")
            result = await asyncio.wait_for(
                self.snmp.walk(oid),
                timeout=15.0
            )
            return result if result else []
        except asyncio.TimeoutError:
            self.logger.error(f"SNMP WALK TIMEOUT: {description}")
            return []
        except Exception as e:
            self.logger.error(f"SNMP WALK ERROR: {description} - {str(e)}")
            return []
    
    async def _safe_get(self, oid: str, description: str = ""):
        """Safe SNMP GET with timeout"""
        try:
            result = await asyncio.wait_for(
                self.snmp.get(oid),
                timeout=5.0
            )
            return result
        except Exception as e:
            self.logger.debug(f"SNMP GET ERROR: {description} - {str(e)}")
            return None
    
    async def _safe_set(self, oid: str, value, value_type, description: str = "") -> bool:
        """Safe SNMP SET with timeout - returns True if successful"""
        try:
            result = await asyncio.wait_for(
                self.snmp.set(oid, value, value_type),
                timeout=5.0
            )
            return result is not None
        except Exception as e:
            self.logger.debug(f"SNMP SET: {description} - {str(e)}")
            return False
    
    async def find_cm_index(self, mac_address: str) -> int | None:
        """Find CM index from MAC address."""
        # Normalize MAC to bytes for comparison
        mac_clean = mac_address.upper().replace('-', '').replace(':', '')
        mac_bytes = bytes.fromhex(mac_clean)
        
        walk_result = await self._safe_walk(self.CM_REG_STATUS_MAC, "Find CM by MAC")
        
        for oid, value in walk_result:
            # Compare as bytes (OctetString returns raw bytes)
            try:
                if hasattr(value, 'asOctets'):
                    val_bytes = value.asOctets()
                elif isinstance(value, bytes):
                    val_bytes = value
                else:
                    # Try to get raw bytes from the value
                    val_bytes = bytes(value)
                
                if val_bytes == mac_bytes:
                    # Extract CM index from OID suffix
                    oid_str = str(oid)
                    idx = oid_str.split('.')[-1]
                    return int(idx)
            except Exception:
                pass
        return None
    
    async def get_modem_us_channels(self, cm_index: int) -> list[int]:
        """Get modem's upstream channel ifIndexes."""
        channels = []
        walk_result = await self._safe_walk(self.CM_US_STATUS_RXPOWER, "Get CM US channels")
        
        # OID base is 1.3.6.1.4.1.4491.2.1.20.1.4.1.2
        # Full OID format: {base}.{cm_idx}.{us_ch_ifindex}
        base_oid = self.CM_US_STATUS_RXPOWER
        
        for oid, value in walk_result:
            oid_str = str(oid)
            # Extract the suffix after base OID: "{cm_idx}.{us_ch}"
            if oid_str.startswith(base_oid):
                suffix = oid_str[len(base_oid) + 1:]  # Skip the dot
                parts = suffix.split('.')
                if len(parts) >= 2:
                    try:
                        cm_idx = int(parts[0])
                        us_ch = int(parts[1])
                        if cm_idx == cm_index:
                            channels.append(us_ch)
                    except ValueError:
                        pass
        return list(set(channels))
    
    async def get_rf_ports(self) -> list[int]:
        """Get all UTSC RF port ifIndexes."""
        rf_ports = []
        walk_result = await self._safe_walk(self.UTSC_CFG_LOGICAL_CH, "Get UTSC RF ports")
        
        for oid, value in walk_result:
            oid_str = str(oid)
            parts = oid_str.split('.')
            for p in parts:
                try:
                    ifidx = int(p)
                    if ifidx > 1000000000:  # RF port ifindexes are large
                        rf_ports.append(ifidx)
                        break
                except:
                    pass
        return list(set(rf_ports))
    
    async def get_rf_port_description(self, rf_port: int) -> str:
        """Get RF port interface description."""
        result = await self._safe_get(f"1.3.6.1.2.1.2.2.1.2.{rf_port}", "ifDescr")
        if result:
            for oid, val in result:
                return str(val)
        return f"RF Port {rf_port}"
    
    async def test_logical_channel_on_rf_port(self, rf_port: int, logical_ch: int) -> bool:
        """Test if logical channel can be set on RF port (validates it belongs to that port)."""
        oid = f"{self.UTSC_CFG_LOGICAL_CH}.{rf_port}.1"
        success = await self._safe_set(oid, logical_ch, Integer32, f"Test ch {logical_ch} on RF {rf_port}")
        if success:
            # Reset to 0 after successful test
            await self._safe_set(oid, 0, Integer32, "Reset logical channel")
        return success
    
    async def discover(self, mac_address: str) -> dict:
        """Discover the correct RF port for a modem."""
        result = {
            "success": False,
            "rf_port_ifindex": None,
            "rf_port_description": None,
            "cm_index": None,
            "us_channels": [],
            "error": None
        }
        
        self.logger.info(f"Discovering RF port for modem {mac_address}")
        
        # Step 1: Find CM index
        cm_index = await self.find_cm_index(mac_address)
        if not cm_index:
            result["error"] = f"Modem {mac_address} not found on CMTS"
            return result
        result["cm_index"] = cm_index
        self.logger.info(f"Found CM index: {cm_index}")
        
        # Step 2: Get modem's upstream channels
        us_channels = await self.get_modem_us_channels(cm_index)
        if not us_channels:
            result["error"] = f"No upstream channels found for CM index {cm_index}"
            return result
        result["us_channels"] = us_channels
        self.logger.info(f"Found {len(us_channels)} upstream channels")
        
        # Step 3: Get all RF ports
        rf_ports = await self.get_rf_ports()
        if not rf_ports:
            result["error"] = "No UTSC RF ports found on CMTS"
            return result
        self.logger.info(f"Found {len(rf_ports)} RF ports")
        
        # Step 4: Test which RF port accepts the logical channel
        first_ch = us_channels[0]
        for rf_port in rf_ports:
            if await self.test_logical_channel_on_rf_port(rf_port, first_ch):
                result["success"] = True
                result["rf_port_ifindex"] = rf_port
                result["rf_port_description"] = await self.get_rf_port_description(rf_port)
                self.logger.info(f"Found matching RF port: {rf_port}")
                return result
        
        result["error"] = f"No RF port found for upstream channel {first_ch}"
        return result
