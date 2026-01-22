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
        repeat_period_ms: int = 1000,
        freerun_duration_ms: int = 60000,
        trigger_count: int = 10
    ) -> dict:
        """Configure UTSC with comprehensive error handling and timeouts"""
        try:
            self.logger.info(f"Starting UTSC configuration for CMTS={self.cmts_ip}, RF Port={self.rf_port_ifindex}")
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            bulk_idx = f".{self.cfg_idx}"
            errors = []
            
            # Check if row already exists
            row_exists = await self._check_row_exists(idx)
            self.logger.info(f"UTSC row exists check: {row_exists}")
            
            # 1. Configure Bulk Data Transfer (TFTP) - these are critical
            self.logger.info("Step 1: Configuring Bulk Data Transfer (TFTP)")
            try:
                ip_parts = tftp_ip.split(".")
                ip_hex = bytes([int(p) for p in ip_parts])
                
                if not await self._safe_snmp_set(f"{self.BULK_CFG_BASE}.3{bulk_idx}", 1, Integer32, "TFTP IP Type (IPv4)"):
                    errors.append("Failed to set TFTP IP type")
                
                if not await self._safe_snmp_set(f"{self.BULK_CFG_BASE}.4{bulk_idx}", ip_hex, OctetString, f"TFTP IP Address {tftp_ip}"):
                    errors.append("Failed to set TFTP IP address")
                
                if not await self._safe_snmp_set(f"{self.BULK_CFG_BASE}.6{bulk_idx}", "", OctetString, "TFTP Base URI (empty)"):
                    errors.append("Failed to set TFTP base URI")
                
                if not await self._safe_snmp_set(f"{self.BULK_CFG_BASE}.7{bulk_idx}", 1, Integer32, "TFTP Protocol"):
                    errors.append("Failed to set TFTP protocol")
                
                # Enable local store to produce file
                if not await self._safe_snmp_set(f"{self.BULK_CFG_BASE}.8{bulk_idx}", 1, Integer32, "Local Store = true (produce file)"):
                    errors.append("Failed to enable local store")
                    
            except Exception as e:
                errors.append(f"TFTP config error: {str(e)}")
            
            # 2. Enable auto upload (optional - may not exist on all CMTS)
            self.logger.info("Step 2: Enabling auto upload (optional)")
            await self._safe_snmp_set(self.BULK_UPLOAD_CONTROL, 1, Integer32, "Bulk Upload Control (optional)")
            
            # 3. Stop measurement first if row exists (allows modifying parameters)
            if row_exists:
                self.logger.info("Step 3: Stopping existing measurement before reconfiguring")
                # MeasStatus: 1=initiate, 2=inactive/stop
                await self._safe_snmp_set(f"{self.UTSC_CTRL_BASE}.1{idx}", 2, Integer32, "MeasStatus = stop")
                import asyncio
                await asyncio.sleep(0.3)  # Give CMTS time to stop
                
                # Try to destroy row for clean reconfiguration
                self.logger.info("Step 3a: Attempting to destroy row for fresh parameters")
                if await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.21{idx}", 6, Integer32, "Row Status destroy"):
                    self.logger.info("Successfully destroyed existing row, will create new one")
                    row_exists = False  # Now we need to create it
                    await asyncio.sleep(0.5)  # Give CMTS time to clean up
                else:
                    # Can't delete, try to set to notInService to modify
                    self.logger.warning("Cannot destroy row, trying notInService instead")
                    if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.21{idx}", 2, Integer32, "Row Status notInService"):
                        self.logger.warning("Row is locked but will try to overwrite parameters anyway")
            
            if not row_exists:
                self.logger.info("Step 3: Creating new UTSC row with createAndWait")
                if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.21{idx}", 4, Integer32, "Row Status createAndWait"):
                    errors.append("Failed to create UTSC row")
            
            # 3a. Set DestinationIndex to enable Bulk File Transfer
            self.logger.info("Step 3a: Setting DestinationIndex to enable auto-upload")
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.24{idx}", 1, Unsigned32, "DestinationIndex = 1 (enable bulk transfer)"):
                errors.append("Failed to set DestinationIndex - bulk transfer may not work")            
            # 4. Configure UTSC timing parameters
            self.logger.info("Step 4: Configuring UTSC timing parameters")
            # Convert milliseconds to microseconds for RepeatPeriod
            repeat_period_us = repeat_period_ms * 1000
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.18{idx}", repeat_period_us, Unsigned32, f"Repeat Period ({repeat_period_ms}ms = {repeat_period_us} microseconds)"):
                errors.append(f"Failed to set RepeatPeriod to {repeat_period_ms}ms - may exceed CMTS maximum (1000ms on CommScope E6000)")
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.19{idx}", freerun_duration_ms, Unsigned32, f"FreeRun Duration ({freerun_duration_ms}ms)"):
                errors.append(f"Failed to set FreeRunDuration to {freerun_duration_ms}ms - may exceed CMTS maximum (600000ms = 10 minutes)")
            # For FreeRunning mode (trigger_mode=2), skip TriggerCount - E6000 uses FreeRunDuration instead
            # E6000 doesn't accept TriggerCount=0 (returns inconsistentValue)
            if trigger_mode != 2:
                if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.20{idx}", trigger_count, Unsigned32, f"Trigger Count ({trigger_count})"):
                    errors.append(f"Failed to set TriggerCount to {trigger_count}")
            
            # 5. Configure UTSC capture parameters
            self.logger.info("Step 5: Configuring UTSC capture parameters")
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.3{idx}", trigger_mode, Integer32, f"Trigger Mode ({trigger_mode})"):
                errors.append("Failed to set trigger mode")
            
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.8{idx}", center_freq_hz, Unsigned32, f"Center Freq ({center_freq_hz} Hz)"):
                errors.append("Failed to set center frequency")
            
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.9{idx}", span_hz, Unsigned32, f"Span ({span_hz} Hz)"):
                errors.append("Failed to set span")
            
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.10{idx}", num_bins, Unsigned32, f"Num Bins ({num_bins})"):
                errors.append("Failed to set num bins")
            
            if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.12{idx}", filename, OctetString, f"Filename ({filename})"):
                errors.append("Failed to set filename")
            
            # 6. Configure CM MAC for trigger mode 6
            if trigger_mode == 6 and cm_mac:
                self.logger.info("Step 6: Configuring CM MAC trigger")
                if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.6{idx}", cm_mac, OctetString, f"CM MAC ({cm_mac})"):
                    errors.append("Failed to set CM MAC")
                
                if logical_ch_ifindex:
                    await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.2{idx}", logical_ch_ifindex, Integer32, f"Logical Ch ifIndex ({logical_ch_ifindex})")
            
            # 7. Activate the row (only if we created it new)
            if not row_exists:
                self.logger.info("Step 7: Activating new UTSC row")
                if not await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.21{idx}", 1, Integer32, "Row Status active"):
                    errors.append("Failed to activate UTSC row")
            else:
                self.logger.info("Step 7: Row already active, setting back to active")
                # Row already exists and is active, just ensure it's active
                await self._safe_snmp_set(f"{self.UTSC_CFG_BASE}.21{idx}", 1, Integer32, "Row Status active (refresh)")
            
            if errors:
                error_msg = "; ".join(errors)
                self.logger.error(f"UTSC configuration completed with errors: {error_msg}")
                return {"success": False, "error": error_msg, "partial": True}
            
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
            idx = f".{self.rf_port_ifindex}.{self.cfg_idx}"
            oid = f"{self.UTSC_CTRL_BASE}.1{idx}"  # docsPnmCmtsUtscCtrlInitiateTest
            
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
