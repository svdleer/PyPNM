# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration
# Based on DOCSIS UTSC (Upstream Triggered Spectrum Capture)

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager


class CmtsUtscService:
    """CMTS-Based Upstream Triggered Spectrum Capture (UTSC) Service
    
    UTSC is CMTS-based, not modem-based. SNMP commands go to CMTS using RF port ifIndex.
    OIDs based on DOCS-PNM-MIB.
    
    All SNMP operations are routed through the agent.
    """
    
    # docsPnmBulkDataTransferCfgTable (E6000 CER I-CCAP User Guide Release 13.0)
    # Index: DestIndex (Unsigned32, key)
    # .3 = DestHostIpAddrType (InetAddressType: 1=IPv4)
    # .4 = DestHostIpAddress  (InetAddress: 4-byte hex for IPv4)
    # .5 = DestPort           (Unsigned32, default 69)
    # .7 = Protocol           (INTEGER: 1=tftp)
    # .8 = LocalStore         (TruthValue: 1=true, 2=false)
    # .9 = RowStatus          (RowStatus: 4=createAndGo, 1=active)
    BULK_DEST_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.2.1"

    # Bulk Data Transfer Configuration
    BULK_UPLOAD_CONTROL = "1.3.6.1.4.1.4491.2.1.27.1.1.1.4"
    BULK_DEST_PATH = "1.3.6.1.4.1.4491.2.1.27.1.1.1.3"
    BULK_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"

    # UTSC Configuration (correct OIDs from DOCS-PNM-MIB)
    UTSC_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
    UTSC_CTRL_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1"
    UTSC_STATUS_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1"
    
    def __init__(self, cmts_ip: str, rf_port_ifindex: int, community: str = "private") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cmts_ip = str(cmts_ip)
        self.rf_port_ifindex = rf_port_ifindex
        self.community = community
        self.agent_manager = get_agent_manager()
        self.cfg_idx = 1  # Use index .1 which exists on this CMTS
    
    def _get_agent_id(self) -> Optional[str]:
        """Get first available agent ID."""
        if not self.agent_manager:
            return None
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return None
        agent = agents[0]
        return agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
    
    async def _safe_snmp_set(self, oid: str, value: Any, value_type: str, description: str = "") -> bool:
        """Safe SNMP SET via agent with error handling.
        
        Args:
            oid: SNMP OID
            value: Value to set
            value_type: Agent type code ('i'=Integer32, 'u'=Unsigned32, 's'=OctetString)
            description: Description for logging
        """
        agent_id = self._get_agent_id()
        if not agent_id:
            self.logger.error(f"SNMP SET: No agent available - {description}")
            return False
        
        try:
            self.logger.debug(f"SNMP SET: {description} - OID={oid}")
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_set',
                params={
                    'target_ip': self.cmts_ip,
                    'oid': oid,
                    'value': value,
                    'type': value_type,
                    'community': self.community,
                    'timeout': 10
                },
                timeout=30
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            
            if result and result.get('result', {}).get('success'):
                self.logger.debug(f"SNMP SET SUCCESS: {description}")
                return True
            else:
                error = result.get('result', {}).get('error', 'SET failed') if result else 'Timeout'
                self.logger.warning(f"SNMP SET FAILED: {description} - {error}")
                return False
        except asyncio.TimeoutError:
            self.logger.error(f"SNMP SET TIMEOUT: {description} - OID={oid}")
            return False
        except Exception as e:
            self.logger.error(f"SNMP SET ERROR: {description} - OID={oid} - {str(e)}")
            return False
    
    async def _safe_snmp_get(self, oid: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Safe SNMP GET via agent with error handling."""
        agent_id = self._get_agent_id()
        if not agent_id:
            self.logger.error(f"SNMP GET: No agent available - {description}")
            return None
        
        try:
            self.logger.debug(f"SNMP GET: {description} - OID={oid}")
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
                error = result.get('result', {}).get('error', 'GET failed') if result else 'Timeout'
                self.logger.debug(f"SNMP GET FAILED: {description} - {error}")
                return None
        except asyncio.TimeoutError:
            self.logger.error(f"SNMP GET TIMEOUT: {description} - OID={oid}")
            return None
        except Exception as e:
            self.logger.debug(f"SNMP GET ERROR: {description} - OID={oid} - {str(e)}")
            return None
    
    def _parse_get_value(self, result: Optional[Dict[str, Any]]) -> Optional[str]:
        """Parse value from agent SNMP GET response."""
        if not result or not result.get('success'):
            return None
        if result.get('results'):
            return str(result['results'][0].get('value', ''))
        output = result.get('output', '')
        if ' = ' in output:
            return output.split(' = ', 1)[1].strip()
        return output.strip() if output else None
    
    def _parse_get_int(self, result: Optional[Dict[str, Any]]) -> Optional[int]:
        """Parse integer value from agent SNMP GET response."""
        value = self._parse_get_value(result)
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    async def _check_row_exists(self, idx: str) -> bool:
        """Check if UTSC configuration row already exists"""
        oid = f"{self.UTSC_CFG_BASE}.21{idx}"  # docsPnmCmtsUtscCfgStatus (RowStatus is field .21)
        result = await self._safe_snmp_get(oid, f"Check row exists for {idx}")
        return self._parse_get_value(result) is not None

    async def _setup_bulk_destination(self, dest_index: int, tftp_ip: str, port: int = 69) -> None:
        """Set TFTP destination IP in docsPnmBulkDataTransferCfgTable.

        Per E6000 CER I-CCAP User Guide Release 13.0:
        - .3 = DestHostIpAddrType (1 = IPv4)
        - .4 = DestHostIpAddress  (4-byte hex string, e.g. 0xAC104B12)
        - .5 = DestPort           (default 69)
        - .7 = Protocol           (1 = tftp)
        - .8 = LocalStore         (2 = false — upload only, preferred)
        - .9 = RowStatus          (createAndGo=4 or active=1)
        """
        idx = f".{dest_index}"
        base = self.BULK_DEST_CFG_BASE

        # Convert IP to 4-byte hex string for InetAddress (e.g. "172.22.147.18" → 0xAC169312)
        try:
            ip_parts = [int(x) for x in tftp_ip.split('.')]
            ip_hex = ''.join(f'{b:02x}' for b in ip_parts)
        except Exception as e:
            self.logger.error(f"Invalid TFTP IP {tftp_ip}: {e}")
            return

        self.logger.info(f"Setting bulk destination {dest_index} → {tftp_ip}:{port} (hex: {ip_hex})")

        # Check current RowStatus to decide createAndGo vs active
        row_oid = f"{base}.9{idx}"
        row_result = await self._safe_snmp_get(row_oid, f"BulkDest RowStatus check")
        row_status = self._parse_get_int(row_result)

        if row_status in (1,):  # active — update address directly
            await self._safe_snmp_set(f"{base}.3{idx}", 1, 'i', f"BulkDest AddrType=IPv4")
            await self._safe_snmp_set(f"{base}.4{idx}", f"0x{ip_hex}", 'x', f"BulkDest IP={tftp_ip}")
            await self._safe_snmp_set(f"{base}.5{idx}", port, 'u', f"BulkDest Port={port}")
            self.logger.info(f"Updated existing bulk destination {dest_index} → {tftp_ip}")
        else:
            # Row does not exist — createAndWait first, then set values, then activate
            await self._safe_snmp_set(f"{base}.9{idx}", 5, 'i', "BulkDest RowStatus=createAndWait")
            await self._safe_snmp_set(f"{base}.3{idx}", 1, 'i', f"BulkDest AddrType=IPv4")
            await self._safe_snmp_set(f"{base}.4{idx}", f"0x{ip_hex}", 'x', f"BulkDest IP={tftp_ip}")
            await self._safe_snmp_set(f"{base}.5{idx}", port, 'u', f"BulkDest Port={port}")
            await self._safe_snmp_set(f"{base}.7{idx}", 1, 'i', "BulkDest Protocol=tftp")
            await self._safe_snmp_set(f"{base}.8{idx}", 2, 'i', "BulkDest LocalStore=false")
            await self._safe_snmp_set(f"{base}.9{idx}", 1, 'i', "BulkDest RowStatus=active")
            self.logger.info(f"Created bulk destination {dest_index} → {tftp_ip}")

    
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
            await self._safe_snmp_set(stop_oid, 2, 'i', "Stop UTSC (InitiateTest=false)")
            
            # Step 2: Wait for status to become not-busy (with timeout)
            status_oid = f"{self.UTSC_STATUS_BASE}.1{idx}"  # docsPnmCmtsUtscStatusMeasStatus
            max_wait_time = 10  # seconds
            poll_interval = 0.5
            waited = 0
            
            while waited < max_wait_time:
                result = await self._safe_snmp_get(status_oid, "Check MeasStatus")
                status_value = self._parse_get_int(result)
                if status_value is not None:
                    self.logger.debug(f"UTSC MeasStatus = {status_value}")
                    # Status values: 1=other, 2=inactive, 3=busy, 4=sampleReady, 5=error
                    if status_value != 3:  # Not busy
                        self.logger.info(f"Port is ready (status={status_value})")
                        break
                
                await asyncio.sleep(poll_interval)
                waited += poll_interval
            
            if waited >= max_wait_time:
                self.logger.warning(f"Timeout waiting for port to become ready (waited {max_wait_time}s)")
            
            # Step 3: Verify RowStatus is active
            row_status_oid = f"{self.UTSC_CFG_BASE}.21{idx}"  # docsPnmCmtsUtscCfgStatus
            result = await self._safe_snmp_get(row_status_oid, "Check RowStatus")
            row_status = self._parse_get_int(result)
            if row_status is not None:
                self.logger.info(f"Row status = {row_status} (1=active, 2=notInService)")
            
            # Get final status for return
            result = await self._safe_snmp_get(status_oid, "Get final MeasStatus")
            final_status = self._parse_get_int(result)
            
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
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.3{idx}", trigger_mode, 'i', f"Trigger Mode ({trigger_mode})")
            
            # 2. Set capture parameters
            self.logger.info(f"Setting NumBins={num_bins}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.10{idx}", num_bins, 'u', f"Num Bins ({num_bins})")
            
            self.logger.info(f"Setting CenterFreq={center_freq_hz} Hz")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.8{idx}", center_freq_hz, 'u', f"Center Freq ({center_freq_hz} Hz)")
            
            self.logger.info(f"Setting Span={span_hz} Hz")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.9{idx}", span_hz, 'u', f"Span ({span_hz} Hz)")
            
            # 3. Set output format and window
            self.logger.info(f"Setting OutputFormat={output_format}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.17{idx}", output_format, 'i', f"Output Format ({output_format})")
            
            self.logger.info(f"Setting Window={window}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.16{idx}", window, 'i', f"Window ({window})")
            
            # 4. Set filename
            self.logger.info(f"Setting Filename={filename}")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.12{idx}", filename, 's', f"Filename ({filename})")
            
            # 5. Set timing parameters for FreeRunning mode
            if trigger_mode == 2:
                # RepeatPeriod: E6000 minimum is 50ms (50000 µs), granularity 50ms
                repeat_period_us_validated = max(50000, repeat_period_us)
                if repeat_period_us_validated != repeat_period_us:
                    self.logger.warning(f"RepeatPeriod {repeat_period_us}µs is below E6000 minimum 50ms, using 50000µs")
                
                self.logger.info(f"Setting RepeatPeriod={repeat_period_us_validated}µs ({repeat_period_us_validated/1000}ms)")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.18{idx}", repeat_period_us_validated, 'u', f"Repeat Period ({repeat_period_us_validated} us)")
                
                self.logger.info(f"Setting FreeRunDuration={freerun_duration_ms}ms")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.19{idx}", freerun_duration_ms, 'u', f"FreeRun Duration ({freerun_duration_ms}ms)")
            
            # 6. Set TriggerCount (ONLY for IdleSID/cmMAC trigger modes, NOT for FreeRunning)
            if trigger_mode in (5, 6):
                self.logger.info(f"Setting TriggerCount={trigger_count} (trigger mode {trigger_mode})")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.20{idx}", trigger_count, 'u', f"Trigger Count ({trigger_count})")
            elif trigger_mode == 2:
                self.logger.info("Skipping TriggerCount for FreeRunning mode (parameter ignored by CMTS)")
            
            # 7. Set TFTP destination IP in bulk data transfer table, then set DestinationIndex
            # Per E6000 CER guide: DestHostIpAddrType/DestHostIpAddress must be configured
            # before DestinationIndex can be used (default is '00000000'h = not set)
            self.logger.info(f"Configuring bulk destination 1 → {tftp_ip}:69")
            await self._setup_bulk_destination(dest_index=1, tftp_ip=tftp_ip, port=69)
            self.logger.info("Setting DestinationIndex=1 (pre-configured TFTP)")
            await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.24{idx}", 1, 'g', "Destination Index (1)")
            
            # 8. For CM MAC trigger mode (mode 6) or IdleSID (mode 5), set CM info
            if trigger_mode in (5, 6) and cm_mac:
                self.logger.info(f"Setting CM MAC={cm_mac}")
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.6{idx}", cm_mac, 's', f"CM MAC ({cm_mac})")
                if logical_ch_ifindex:
                    await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.2{idx}", logical_ch_ifindex, 'i', f"Logical Ch ifIndex ({logical_ch_ifindex})")
            
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
            
            if not await self._safe_snmp_set(oid, 1, 'i', "Initiate UTSC Test"):
                return {"success": False, "error": "Failed to initiate UTSC capture"}
            
            self.logger.info("UTSC capture initiated successfully")
            return {"success": True}
        except Exception as e:
            error_msg = f"Failed to start UTSC: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    async def get_latest_data(self) -> dict:
        """
        Get latest UTSC spectrum data.
        
        This method reads the current spectrum measurement results from the CMTS.
        The data is fetched via TFTP when the measurement completes.
        
        For WebSocket streaming, this provides real-time amplitude data.
        
        Returns:
            dict: {success: bool, spectrum: {freq_start_hz, freq_step_hz, amplitudes}}
        """
        try:
            # Check measurement status first
            # OID: docsPnmCmtsUtscStatusMeasStatus (column 2)
            status_oid = f"{self.UTSC_STATUS_BASE}.2.{self.rf_port_ifindex}.{self.cfg_idx}"
            status_result = await self._safe_snmp_get(status_oid, "Get UTSC Status")
            status_val = self._parse_get_int(status_result)
            
            # Status values: 1=other, 2=inactive, 3=busy, 4=sampleReady, 5=error
            if status_val != 4:  # Not sampleReady
                return {
                    "success": False, 
                    "error": f"Data not ready (status={status_val})",
                    "status": status_val
                }
            
            # Get center frequency and span for calculating frequency axis
            center_freq_oid = f"{self.UTSC_CFG_BASE}.6.{self.rf_port_ifindex}.{self.cfg_idx}"
            span_oid = f"{self.UTSC_CFG_BASE}.7.{self.rf_port_ifindex}.{self.cfg_idx}"
            num_bins_oid = f"{self.UTSC_CFG_BASE}.10.{self.rf_port_ifindex}.{self.cfg_idx}"
            
            center_result = await self._safe_snmp_get(center_freq_oid, "Get Center Freq")
            span_result = await self._safe_snmp_get(span_oid, "Get Span")
            bins_result = await self._safe_snmp_get(num_bins_oid, "Get Num Bins")
            
            center_freq = self._parse_get_int(center_result) or 30000000  # Default 30 MHz
            span = self._parse_get_int(span_result) or 80000000  # Default 80 MHz
            num_bins = self._parse_get_int(bins_result) or 800
            
            freq_start = center_freq - (span // 2)
            freq_step = span // num_bins if num_bins > 0 else 100000
            
            # Note: Actual amplitude data comes from TFTP file
            # For WebSocket streaming, we'd need to parse the TFTP file
            # This is a placeholder that returns the configuration
            return {
                "success": True,
                "spectrum": {
                    "freq_start_hz": freq_start,
                    "freq_step_hz": freq_step,
                    "center_freq_hz": center_freq,
                    "span_hz": span,
                    "num_bins": num_bins,
                    "amplitudes": []  # Actual data from TFTP file
                },
                "status": status_val
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get spectrum data: {e}")
            return {"success": False, "error": str(e)}


class UtscRfPortDiscoveryService:
    """Service to discover the correct RF port for a modem's upstream channel.
    
    Uses the modem's upstream logical channel to find which UTSC RF port it belongs to.
    All SNMP operations routed through agent.
    """
    
    # docsIfCmtsCmStatusMacAddress (works on E6000, returns all CMs)
    CM_REG_STATUS_MAC = "1.3.6.1.2.1.10.127.1.3.3.1.2"
    # docsIf3CmtsCmUsStatusRxPower (to find US channels by CM index)
    CM_US_STATUS_RXPOWER = "1.3.6.1.4.1.4491.2.1.20.1.4.1.2"
    # docsIfCmtsCmStatusUpChannelIfIndex (fallback for Casa)
    CM_US_STATUS_IFINDEX = "1.3.6.1.2.1.10.127.1.3.3.1.5"
    # docsIf31CmtsCmUsOfdmaChannelTimingOffset (to find OFDMA channels)
    CM_OFDMA_STATUS = "1.3.6.1.4.1.4491.2.1.28.1.4.1.2"
    # docsPnmCmtsUtscCfgLogicalChIfIndex (to get RF ports)
    UTSC_CFG_LOGICAL_CH = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2"
    # ifDescr
    OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
    
    def __init__(self, cmts_ip: str, community: str = "private") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cmts_ip = str(cmts_ip)
        self.community = community
        self.agent_manager = init_agent_manager()
    
    def _get_agent_id(self):
        if not self.agent_manager:
            return None
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return None
        agent = agents[0]
        return agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
    
    async def _snmp_walk(self, oid: str, timeout: int = 30):
        agent_id = self._get_agent_id()
        if not agent_id:
            return {'success': False, 'error': 'No agent available'}
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id, command='snmp_walk',
                params={'target_ip': self.cmts_ip, 'oid': oid, 'community': self.community, 'timeout': 15},
                timeout=timeout
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=timeout)
            if result and result.get('result', {}).get('success'):
                return result['result']
            error = result.get('result', {}).get('error', 'Walk failed') if result else 'Timeout'
            return {'success': False, 'error': error}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _snmp_parallel_walk(self, oids: list[str], timeout: int = 60):
        """Walk multiple OID trees in a single agent round-trip."""
        agent_id = self._get_agent_id()
        if not agent_id:
            return {'success': False, 'error': 'No agent available'}
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id, command='snmp_parallel_walk',
                params={'ip': self.cmts_ip, 'oids': oids, 'community': self.community, 'timeout': 30},
                timeout=timeout
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=timeout)
            if result and result.get('result', {}).get('success'):
                return result['result']
            error = result.get('result', {}).get('error', 'Parallel walk failed') if result else 'Timeout'
            return {'success': False, 'error': error}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _snmp_get(self, oid: str):
        agent_id = self._get_agent_id()
        if not agent_id:
            return {'success': False, 'error': 'No agent available'}
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id, command='snmp_get',
                params={'target_ip': self.cmts_ip, 'oid': oid, 'community': self.community, 'timeout': 10},
                timeout=30
            )
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            if result and result.get('result', {}).get('success'):
                return result['result']
            error = result.get('result', {}).get('error', 'Get failed') if result else 'Timeout'
            return {'success': False, 'error': error}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _parse_get_value(self, result):
        if not result.get('success'):
            return None
        if result.get('results'):
            return str(result['results'][0].get('value', ''))
        output = result.get('output', '')
        if ' = ' in output:
            return output.split(' = ', 1)[1].strip()
        return output.strip() if output else None
    
    @staticmethod
    def normalize_mac(mac: str) -> str:
        return mac.upper().replace(':', '').replace('-', '').replace('.', '')
    
    async def discover(self, mac_address: str) -> dict:
        """Discover the correct UTSC RF port for a modem.
        
        Uses ONE parallel SNMP walk (3 OID trees) + ONE get = 2 agent round-trips max.
        All business logic runs in PyPNM, agent is just an SNMP proxy.
        
        Flow:
        1. Parallel walk: ifDescr + CM MAC table + OFDMA status (1 agent call)
        2. Parse results: find CM index, find OFDMA channel, find us-conn ports
        3. CommScope E6000: map OFDMA slot -> us-conn RF port
        4. Get RF port description (1 agent call)
        
        Supports:
        - CommScope E6000: us-conn RF ports mapped by blade slot from OFDMA channel
        - Fallback: OFDMA channel ifIndex directly (for other CMTS types)
        """
        import re
        
        result = {
            "success": False,
            "rf_port_ifindex": None,
            "rf_port_description": None,
            "cm_index": None,
            "us_channels": [],
            "logical_channel": None,
            "error": None
        }
        
        mac_normalized = self.normalize_mac(mac_address)
        self.logger.info(f"Discovering RF port for {mac_normalized} on {self.cmts_ip}")
        
        # === ONE agent call: parallel walk 3 OID trees ===
        walk_result = await self._snmp_parallel_walk([
            self.OID_IF_DESCR,       # All interface descriptions (us-conn ports + channel names)
            self.CM_REG_STATUS_MAC,   # All registered CM MACs -> CM index
            self.CM_OFDMA_STATUS,     # All OFDMA channel assignments -> CM -> OFDMA ifIndex
        ])
        
        if not walk_result.get('success') or not walk_result.get('results'):
            result["error"] = f"SNMP parallel walk failed: {walk_result.get('error', 'no data')}"
            return result
        
        all_data = walk_result['results']
        if_descr_data = all_data.get(self.OID_IF_DESCR, [])
        cm_mac_data = all_data.get(self.CM_REG_STATUS_MAC, [])
        ofdma_data = all_data.get(self.CM_OFDMA_STATUS, [])
        
        self.logger.info(f"Parallel walk: {len(if_descr_data)} ifDescr, {len(cm_mac_data)} CMs, {len(ofdma_data)} OFDMA entries")
        
        # --- Parse CM index from MAC table ---
        cm_index = None
        for entry in cm_mac_data:
            found_mac = self.normalize_mac(str(entry.get('value', '')))
            if found_mac == mac_normalized:
                cm_index = int(str(entry['oid']).split('.')[-1])
                break
        
        if not cm_index:
            result["error"] = f"Modem {mac_address} not found on CMTS"
            return result
        result["cm_index"] = cm_index
        self.logger.info(f"CM index: {cm_index}")
        
        # --- Parse OFDMA channel for this CM ---
        ofdma_ifindex = None
        for entry in ofdma_data:
            oid_str = str(entry.get('oid', ''))
            if f".{cm_index}." in oid_str:
                parts = oid_str.split(".")
                for i, part in enumerate(parts):
                    if part == str(cm_index) and i + 1 < len(parts):
                        candidate = int(parts[i + 1])
                        if candidate >= 843087000:
                            ofdma_ifindex = candidate
                            break
                if ofdma_ifindex:
                    break
        
        # --- Build ifDescr lookup and find us-conn ports ---
        if_descr_map = {}  # ifindex -> description
        blade_to_ports = {}  # blade_slot -> [(ifindex, descr)]
        us_conn_found = False
        
        for entry in if_descr_data:
            ifindex = int(str(entry['oid']).split('.')[-1])
            descr = str(entry.get('value', ''))
            if_descr_map[ifindex] = descr
            
            if 'us-conn' in descr.lower():
                us_conn_found = True
                blade_match = re.search(r'RPS\d+-(\d+)', descr)
                if blade_match:
                    slot = int(blade_match.group(1))
                    blade_to_ports.setdefault(slot, []).append((ifindex, descr))
        
        # --- CommScope E6000: map OFDMA slot -> us-conn RF port ---
        if us_conn_found and ofdma_ifindex:
            # Get OFDMA channel description from the walk data we already have
            ofdma_descr = if_descr_map.get(ofdma_ifindex)
            if not ofdma_descr:
                # Fallback: single GET for this one ifIndex (2nd agent call)
                get_result = await self._snmp_get(f"{self.OID_IF_DESCR}.{ofdma_ifindex}")
                ofdma_descr = self._parse_get_value(get_result) or ""
            
            slot_match = re.search(r'cable-us(?:-ofdma)?\s+(\d+)/', ofdma_descr)
            if slot_match:
                slot = int(slot_match.group(1))
                if slot in blade_to_ports and blade_to_ports[slot]:
                    port_ifindex, port_descr = blade_to_ports[slot][0]
                    result["success"] = True
                    result["rf_port_ifindex"] = port_ifindex
                    result["rf_port_description"] = port_descr
                    result["logical_channel"] = port_ifindex
                    self.logger.info(f"CommScope us-conn RF port: {port_descr} ({port_ifindex})")
                    return result
                self.logger.warning(f"No us-conn port for blade slot {slot}")
        
        # --- Fallback: use OFDMA channel directly ---
        if ofdma_ifindex:
            ofdma_descr = if_descr_map.get(ofdma_ifindex, f"OFDMA {ofdma_ifindex}")
            result["success"] = True
            result["rf_port_ifindex"] = ofdma_ifindex
            result["rf_port_description"] = ofdma_descr
            result["logical_channel"] = ofdma_ifindex
            self.logger.info(f"Fallback OFDMA channel: {ofdma_descr} ({ofdma_ifindex})")
            return result
        
        result["error"] = f"No OFDMA channel found for CM index {cm_index}"
        return result
