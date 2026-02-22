# SPDX-License-Identifier: Apache-2.0
# PNM Modem Diagnostics Service
#
# This service handles PNM diagnostics for cable modems:
# - RxMER (Receive Modulation Error Ratio)
# - FEC (Forward Error Correction) statistics
# - Channel Power (DS/US)
# - Pre-equalization coefficients
#
# All SNMP queries go through the agent, parsing is done here in the API.

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from pypnm.api.agent.manager import get_agent_manager


class PNMDiagnosticsService:
    """
    Service for PNM modem diagnostics.
    
    Uses agent for raw SNMP operations, performs parsing in API layer.
    """
    
    # ============================================
    # SNMP OID Constants
    # ============================================
    
    # RxMER OIDs
    OID_OFDM_POWER = '1.3.6.1.4.1.4491.2.1.28.1.5'  # docsIf31CmDsOfdmChannelPowerTable
    
    # FEC OIDs
    OID_UNERRORED = '1.3.6.1.2.1.10.127.1.1.4.1.2'       # docsIfSigQUnerroreds
    OID_CORRECTED = '1.3.6.1.2.1.10.127.1.1.4.1.3'       # docsIfSigQCorrecteds
    OID_UNCORRECTABLE = '1.3.6.1.2.1.10.127.1.1.4.1.4'   # docsIfSigQUncorrectables
    OID_SNR = '1.3.6.1.2.1.10.127.1.1.4.1.5'             # docsIfSigQSignalNoise
    
    # Channel Power OIDs
    OID_DS_FREQ = '1.3.6.1.2.1.10.127.1.1.1.1.2'         # docsIfDownChannelFrequency
    OID_DS_POWER = '1.3.6.1.2.1.10.127.1.1.1.1.6'        # docsIfDownChannelPower
    OID_US_POWER = '1.3.6.1.4.1.4491.2.1.20.1.2.1.1'     # docsIf3CmStatusUsTxPower
    
    # Pre-Equalization OIDs
    OID_PRE_EQ = '1.3.6.1.4.1.4491.2.1.20.1.2.1.5'       # docsIf3CmStatusUsEqData
    
    def __init__(self, modem_ip: str, community: str = "public", mac_address: str = None, write_community: str = None):
        self.modem_ip = modem_ip
        self.community = community
        self.write_community = write_community or community  # For SNMP SET operations
        self.mac_address = mac_address
        self.logger = logging.getLogger("PNMDiagnosticsService")
        self.agent_manager = get_agent_manager()
    
    async def _snmp_walk(self, oid: str) -> Dict[str, Any]:
        """Execute SNMP walk via agent."""
        if not self.agent_manager:
            return {'success': False, 'error': 'Agent manager not available'}
        
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available'}
        
        agent = agents[0]
        agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_walk',
                params={
                    'target_ip': self.modem_ip,
                    'oid': oid,
                    'community': self.community,
                    'timeout': 10
                },
                timeout=30
            )
            
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            
            if result and result.get('result', {}).get('success'):
                return result.get('result', {})
            else:
                error = result.get('result', {}).get('error', 'SNMP walk failed') if result else 'Timeout'
                return {'success': False, 'error': error}
                
        except Exception as e:
            self.logger.exception(f"SNMP walk error: {e}")
            return {'success': False, 'error': str(e)}

    async def _snmp_get(self, oid: str, target_ip: str = None) -> Dict[str, Any]:
        """Execute SNMP GET via agent."""
        if not self.agent_manager:
            return {'success': False, 'error': 'Agent manager not available'}
        
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available'}
        
        agent = agents[0]
        agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_get',
                params={
                    'target_ip': target_ip or self.modem_ip,
                    'oid': oid,
                    'community': self.community,
                    'timeout': 10
                },
                timeout=30
            )
            
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            
            if result and result.get('result', {}).get('success'):
                return result.get('result', {})
            else:
                error = result.get('result', {}).get('error', 'SNMP get failed') if result else 'Timeout'
                return {'success': False, 'error': error}
                
        except Exception as e:
            self.logger.exception(f"SNMP get error: {e}")
            return {'success': False, 'error': str(e)}

    async def _snmp_set(self, oid: str, value: Any, value_type: str, target_ip: str = None) -> Dict[str, Any]:
        """Execute SNMP SET via agent (uses write_community)."""
        if not self.agent_manager:
            return {'success': False, 'error': 'Agent manager not available'}
        
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available'}
        
        agent = agents[0]
        agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_set',
                params={
                    'target_ip': target_ip or self.modem_ip,
                    'oid': oid,
                    'value': value,
                    'value_type': value_type,
                    'community': self.write_community,
                    'timeout': 10
                },
                timeout=30
            )
            
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=30)
            
            if result and result.get('result', {}).get('success'):
                return result.get('result', {})
            else:
                error = result.get('result', {}).get('error', 'SNMP set failed') if result else 'Timeout'
                return {'success': False, 'error': error}
                
        except Exception as e:
            self.logger.exception(f"SNMP set error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _snmp_parallel_walk(self, oids: List[str]) -> Dict[str, Any]:
        """Execute parallel SNMP walks via agent."""
        if not self.agent_manager:
            return {'success': False, 'error': 'Agent manager not available'}
        
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available'}
        
        agent = agents[0]
        agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command='snmp_parallel_walk',
                params={
                    'ip': self.modem_ip,
                    'oids': oids,
                    'community': self.community,
                    'timeout': 10
                },
                timeout=60
            )
            
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=60)
            
            if result and result.get('result', {}).get('success'):
                return result.get('result', {})
            else:
                error = result.get('result', {}).get('error', 'SNMP parallel walk failed') if result else 'Timeout'
                return {'success': False, 'error': error}
                
        except Exception as e:
            self.logger.exception(f"SNMP parallel walk error: {e}")
            return {'success': False, 'error': str(e)}

    async def _send_agent_command(self, command: str, params: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        """Send generic command to agent and wait for response."""
        if not self.agent_manager:
            return {'success': False, 'error': 'Agent manager not available'}
        
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available'}
        
        agent = agents[0]
        agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command=command,
                params=params,
                timeout=timeout
            )
            
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=timeout)
            
            if result and result.get('result'):
                return result.get('result', {})
            else:
                return {'success': False, 'error': 'Timeout or no response'}
                
        except Exception as e:
            self.logger.exception(f"Agent command error: {e}")
            return {'success': False, 'error': str(e)}
    
    # ============================================
    # RxMER
    # ============================================
    
    async def get_rxmer(self) -> Dict[str, Any]:
        """
        Get RxMER (Receive Modulation Error Ratio) data from modem.
        
        Returns:
            Dict with 'success', 'measurements', 'error'
        """
        self.logger.info(f"Getting RxMER for modem {self.modem_ip}")
        
        result = await self._snmp_walk(self.OID_OFDM_POWER)
        
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'SNMP query failed'),
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip
            }
        
        # Parse RxMER values from walk results
        measurements = []
        walk_results = result.get('results', [])
        
        for item in walk_results:
            try:
                oid_str = item.get('oid', '')
                value = item.get('value')
                
                # Extract channel index from OID
                idx = oid_str.split('.')[-1]
                
                if value is not None:
                    # Convert value - may be scaled by 10
                    val = int(value) if isinstance(value, (int, float)) else int(str(value))
                    mer_db = val / 10 if abs(val) > 100 else float(val)
                    
                    measurements.append({
                        'channel_id': int(idx),
                        'mer_db': mer_db
                    })
                    
            except Exception as e:
                self.logger.warning(f"Error parsing RxMER item {item}: {e}")
        
        return {
            'success': True,
            'measurements': measurements,
            'mac_address': self.mac_address,
            'modem_ip': self.modem_ip,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    async def trigger_rxmer_measurement(self) -> Dict[str, Any]:
        """
        Trigger async RxMER measurement on the modem via SNMP SET.
        
        This configures the modem to start a PNM RxMER measurement and upload 
        results to TFTP. The measurement takes ~30 seconds to complete.
        
        Returns:
            Dict with 'success', 'message', 'error'
        """
        self.logger.info(f"Triggering async RxMER measurement for modem {self.modem_ip}")
        
        # DOCSIS PNM RxMER measurement OIDs
        # These are the OIDs for configuring DS OFDM RxMER measurement
        OID_RXMER_FILENAME = '1.3.6.1.4.1.4491.2.1.27.1.3.1.1.1.3'    # docsPnmCmDsOfdmRxMerFileName  
        OID_RXMER_ENABLE = '1.3.6.1.4.1.4491.2.1.27.1.3.1.1.1.4'      # docsPnmCmDsOfdmRxMerFileEnable
        
        try:
            # Generate filename based on MAC and timestamp
            import time
            mac_clean = (self.mac_address or "unknown").replace(":", "").lower()
            timestamp = int(time.time())
            filename = f"ds_ofdm_rxmer_per_subcar_{mac_clean}_{timestamp}"
            
            # Step 1: Set filename for RxMER measurement
            result_filename = await self._snmp_set(OID_RXMER_FILENAME, filename, 'OCTET_STRING')
            if not result_filename.get('success'):
                return {
                    'success': False,
                    'error': f"Failed to set RxMER filename: {result_filename.get('error')}",
                    'mac_address': self.mac_address,
                    'modem_ip': self.modem_ip
                }
            
            # Step 2: Trigger measurement (enable = 1)
            result_trigger = await self._snmp_set(OID_RXMER_ENABLE, 1, 'INTEGER')
            if not result_trigger.get('success'):
                return {
                    'success': False,
                    'error': f"Failed to trigger RxMER measurement: {result_trigger.get('error')}",
                    'mac_address': self.mac_address,
                    'modem_ip': self.modem_ip
                }
            
            return {
                'success': True,
                'message': f"RxMER measurement triggered, filename: {filename}",
                'filename': filename,
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.exception(f"Error triggering RxMER measurement: {e}")
            return {
                'success': False,
                'error': str(e),
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip
            }
    
    # ============================================
    # FEC Statistics
    # ============================================
    
    async def get_fec(self) -> Dict[str, Any]:
        """
        Get FEC (Forward Error Correction) statistics from modem.
        
        Returns:
            Dict with 'success', 'channels', 'total_uncorrectable', 'total_corrected', 'error'
        """
        self.logger.info(f"Getting FEC stats for modem {self.modem_ip}")
        
        # Walk all FEC-related OIDs in parallel
        oids = [self.OID_UNERRORED, self.OID_CORRECTED, self.OID_UNCORRECTABLE, self.OID_SNR]
        result = await self._snmp_parallel_walk(oids)
        
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'SNMP query failed'),
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip
            }
        
        raw_results = result.get('results', {})
        
        # Parse each OID's results
        def parse_oid_results(oid: str) -> Dict[str, int]:
            values = {}
            for item in raw_results.get(oid, []):
                try:
                    oid_str = item.get('oid', '')
                    idx = oid_str.split('.')[-1]
                    value = item.get('value')
                    if value is not None:
                        values[idx] = int(value) if isinstance(value, (int, float)) else int(str(value))
                except (ValueError, TypeError):
                    continue
            return values
        
        unerrored_map = parse_oid_results(self.OID_UNERRORED)
        corrected_map = parse_oid_results(self.OID_CORRECTED)
        uncorrectable_map = parse_oid_results(self.OID_UNCORRECTABLE)
        snr_map = parse_oid_results(self.OID_SNR)
        
        # Build channel list
        channels = []
        all_indexes = set(unerrored_map.keys()) | set(corrected_map.keys()) | set(uncorrectable_map.keys())
        
        for idx in sorted(all_indexes, key=lambda x: int(x) if x.isdigit() else 0):
            unerrored = unerrored_map.get(idx, 0)
            corrected = corrected_map.get(idx, 0)
            uncorrectable = uncorrectable_map.get(idx, 0)
            total = unerrored + corrected + uncorrectable
            snr = snr_map.get(idx, 0) / 10 if idx in snr_map else 0
            
            channels.append({
                'channel_id': int(idx) if idx.isdigit() else 0,
                'unerrored': unerrored,
                'corrected': corrected,
                'uncorrectable': uncorrectable,
                'total_codewords': total,
                'snr_db': snr
            })
        
        return {
            'success': True,
            'mac_address': self.mac_address,
            'modem_ip': self.modem_ip,
            'timestamp': datetime.now().isoformat(),
            'channels': channels,
            'total_uncorrectable': sum(c['uncorrectable'] for c in channels),
            'total_corrected': sum(c['corrected'] for c in channels)
        }
    
    # ============================================
    # Channel Power
    # ============================================
    
    async def get_channel_power(self) -> Dict[str, Any]:
        """
        Get channel power data from modem.
        
        Returns:
            Dict with 'success', 'downstream_channels', 'upstream_channels', 'error'
        """
        self.logger.info(f"Getting channel power for modem {self.modem_ip}")
        
        # Walk DS and US OIDs in parallel
        oids = [self.OID_DS_FREQ, self.OID_DS_POWER, self.OID_US_POWER]
        result = await self._snmp_parallel_walk(oids)
        
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'SNMP query failed'),
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip
            }
        
        raw_results = result.get('results', {})
        
        # Parse DS frequency
        freq_map = {}
        for item in raw_results.get(self.OID_DS_FREQ, []):
            try:
                oid_str = item.get('oid', '')
                idx = oid_str.split('.')[-1]
                value = item.get('value')
                if value is not None:
                    freq_map[idx] = int(value)
            except (ValueError, TypeError):
                continue
        
        # Parse DS power and combine with frequency
        ds_channels = []
        for item in raw_results.get(self.OID_DS_POWER, []):
            try:
                oid_str = item.get('oid', '')
                idx = oid_str.split('.')[-1]
                value = item.get('value')
                if value is not None and idx in freq_map:
                    ds_channels.append({
                        'channel_id': int(idx),
                        'frequency_hz': freq_map[idx],
                        'power_dbmv': int(value) / 10
                    })
            except (ValueError, TypeError):
                continue
        
        # Parse US power
        us_channels = []
        for item in raw_results.get(self.OID_US_POWER, []):
            try:
                oid_str = item.get('oid', '')
                idx = oid_str.split('.')[-1]
                value = item.get('value')
                if value is not None:
                    us_channels.append({
                        'channel_id': int(idx),
                        'power_dbmv': int(value) / 10
                    })
            except (ValueError, TypeError):
                continue
        
        return {
            'success': True,
            'mac_address': self.mac_address,
            'modem_ip': self.modem_ip,
            'timestamp': datetime.now().isoformat(),
            'downstream_channels': ds_channels,
            'upstream_channels': us_channels
        }
    
    # ============================================
    # Pre-Equalization Coefficients
    # ============================================
    
    async def get_pre_eq(self) -> Dict[str, Any]:
        """
        Get pre-equalization coefficients from modem.
        
        Returns:
            Dict with 'success', 'coefficients', 'error'
        """
        self.logger.info(f"Getting pre-eq coefficients for modem {self.modem_ip}")
        
        result = await self._snmp_walk(self.OID_PRE_EQ)
        
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'SNMP query failed'),
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip
            }
        
        # Parse pre-eq data
        coefficients = []
        walk_results = result.get('results', [])
        
        for item in walk_results:
            try:
                oid_str = item.get('oid', '')
                idx = oid_str.split('.')[-1]
                value = item.get('value', '')
                
                # Value should be hex string
                hex_data = str(value).strip()
                if hex_data:
                    coefficients.append({
                        'channel_id': int(idx),
                        'hex_data': hex_data,
                        'length': len(hex_data.replace(' ', '').replace(':', '')) // 2
                    })
            except (ValueError, TypeError, IndexError):
                continue
        
        return {
            'success': True,
            'mac_address': self.mac_address,
            'modem_ip': self.modem_ip,
            'timestamp': datetime.now().isoformat(),
            'coefficients': coefficients
        }

    # ============================================
    # Spectrum Analyzer
    # ============================================

    # ============================================
    # Spectrum Analyzer
    # ============================================
    
    # Spectrum Analyzer OIDs (docsIf3CmSpectrumAnalysisCtrlCmd: 1.3.6.1.4.1.4491.2.1.20.1.34)
    OID_BULK_IP_TYPE = '1.3.6.1.4.1.4491.2.1.27.1.1.1.1.0'
    OID_BULK_IP_ADDR = '1.3.6.1.4.1.4491.2.1.27.1.1.1.2.0'
    OID_BULK_UPLOAD_CTRL = '1.3.6.1.4.1.4491.2.1.27.1.1.1.4.0'
    OID_INACTIVITY_TIMEOUT = '1.3.6.1.4.1.4491.2.1.20.1.34.2.0'
    OID_FIRST_SEG_FREQ = '1.3.6.1.4.1.4491.2.1.20.1.34.3.0'
    OID_LAST_SEG_FREQ = '1.3.6.1.4.1.4491.2.1.20.1.34.4.0'
    OID_SEGMENT_SPAN = '1.3.6.1.4.1.4491.2.1.20.1.34.5.0'
    OID_NUM_BINS = '1.3.6.1.4.1.4491.2.1.20.1.34.6.0'
    OID_NOISE_BW = '1.3.6.1.4.1.4491.2.1.20.1.34.7.0'
    OID_WINDOW_FUNC = '1.3.6.1.4.1.4491.2.1.20.1.34.8.0'
    OID_NUM_AVERAGES = '1.3.6.1.4.1.4491.2.1.20.1.34.9.0'
    OID_SPEC_FILE_ENABLE = '1.3.6.1.4.1.4491.2.1.20.1.34.10.0'
    OID_SPEC_STATUS = '1.3.6.1.4.1.4491.2.1.20.1.34.11.0'
    OID_SPEC_FILENAME = '1.3.6.1.4.1.4491.2.1.20.1.34.12.0'
    OID_SPEC_ENABLE = '1.3.6.1.4.1.4491.2.1.20.1.34.1.0'

    async def trigger_spectrum(self, tftp_server: str = '172.22.147.18') -> Dict[str, Any]:
        """
        Trigger DS OFDM spectrum analyzer capture via raw SNMP.
        
        Configures modem to capture full-band spectrum and upload to TFTP.
        
        Returns:
            Dict with 'success', 'filename', etc.
        """
        import asyncio
        from datetime import datetime
        
        self.logger.info(f"Triggering spectrum capture for modem {self.modem_ip}")
        
        try:
            # Step 1: Set TFTP/Bulk destination
            self.logger.info(f"Setting TFTP server: {tftp_server}")
            await self._snmp_set(self.OID_BULK_IP_TYPE, 1, 'i')  # IPv4
            ip_hex = ''.join([f'{int(p):02x}' for p in tftp_server.split('.')])
            await self._snmp_set(self.OID_BULK_IP_ADDR, ip_hex, 'x')
            await self._snmp_set(self.OID_BULK_UPLOAD_CTRL, 3, 'i')  # AUTO_UPLOAD
            
            # Step 2: Configure spectrum parameters
            mac_clean = (self.mac_address or '').replace(':', '').lower()
            timestamp = int(datetime.now().timestamp())
            filename = f"spectrum_{mac_clean}_{timestamp}"
            
            # Spectrum analyzer parameters
            first_seg_freq = 108_000_000  # 108 MHz
            last_seg_freq = 993_000_000   # 993 MHz
            segment_span = 1_000_000      # 1 MHz (2 MHz for Ubee)
            num_bins = 256
            noise_bw = 110
            window_func = 1  # HANN
            num_averages = 1
            inactivity_timeout = 100
            
            self.logger.info(f"Configuring spectrum analyzer parameters...")
            await self._snmp_set(self.OID_INACTIVITY_TIMEOUT, inactivity_timeout, 'i')
            await self._snmp_set(self.OID_FIRST_SEG_FREQ, first_seg_freq, 'i')
            await self._snmp_set(self.OID_LAST_SEG_FREQ, last_seg_freq, 'i')
            await self._snmp_set(self.OID_SEGMENT_SPAN, segment_span, 'i')
            await self._snmp_set(self.OID_NUM_BINS, num_bins, 'i')
            await self._snmp_set(self.OID_NOISE_BW, noise_bw, 'i')
            await self._snmp_set(self.OID_WINDOW_FUNC, window_func, 'i')
            await self._snmp_set(self.OID_NUM_AVERAGES, num_averages, 'i')
            
            # Set filename
            self.logger.info(f"Setting spectrum filename: {filename}")
            await self._snmp_set(self.OID_SPEC_FILENAME, filename, 's')
            
            # Toggle enable FALSE -> TRUE
            await self._snmp_set(self.OID_SPEC_ENABLE, 2, 'i')  # FALSE
            self.logger.info(f"Enabling spectrum analyzer")
            await self._snmp_set(self.OID_SPEC_ENABLE, 1, 'i')  # TRUE
            
            # Enable file output (triggers upload)
            self.logger.info(f"Enabling spectrum file output")
            result = await self._snmp_set(self.OID_SPEC_FILE_ENABLE, 1, 'i')
            if not result.get('success'):
                return {'success': False, 'error': f"Failed to trigger spectrum: {result.get('error')}"}
            
            # Poll status (max 30s)
            max_wait = 30
            poll_interval = 2
            elapsed = 0
            
            self.logger.info(f"Polling spectrum status...")
            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                status_result = await self._snmp_get(self.OID_SPEC_STATUS)
                if status_result.get('success') and status_result.get('results'):
                    status_value = status_result['results'][0].get('value')
                    self.logger.info(f"Spectrum status: {status_value} (after {elapsed}s)")
                    if status_value == 3:  # complete
                        break
            
            return {
                'success': True,
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip,
                'message': 'Spectrum capture triggered',
                'filename': filename,
                'status_polled': elapsed < max_wait
            }
            
        except Exception as e:
            self.logger.exception(f"Spectrum capture error: {e}")
            return {'success': False, 'error': str(e)}

    # ============================================
    # Channel Info
    # ============================================

    # OIDs for channel info
    OID_DS_FREQ_CHAN = '1.3.6.1.2.1.10.127.1.1.1.1.2'          # docsIfDownChannelFrequency
    OID_DS_POWER_CHAN = '1.3.6.1.2.1.10.127.1.1.1.1.6'         # docsIfDownChannelPower
    OID_DS_SNR_CHAN = '1.3.6.1.2.1.10.127.1.1.4.1.5'           # docsIfSigQSignalNoise
    OID_US_POWER_CHAN = '1.3.6.1.4.1.4491.2.1.20.1.2.1.1'      # docsIf3CmStatusUsTxPower
    OID_DS_OFDM_CHAN_ID = '1.3.6.1.4.1.4491.2.1.28.1.9.1.1'    # docsIf31CmDsOfdmChanChannelId
    OID_DS_OFDM_SUBCARRIER_ZERO = '1.3.6.1.4.1.4491.2.1.28.1.9.1.3'
    OID_DS_OFDM_FIRST_ACTIVE = '1.3.6.1.4.1.4491.2.1.28.1.9.1.4'
    OID_DS_OFDM_LAST_ACTIVE = '1.3.6.1.4.1.4491.2.1.28.1.9.1.5'
    OID_DS_OFDM_PLC_FREQ = '1.3.6.1.4.1.4491.2.1.28.1.9.1.10'
    OID_DS_OFDM_POWER = '1.3.6.1.4.1.4491.2.1.28.1.11.1.3'
    OID_DS_OFDM_PROFILES = '1.3.6.1.4.1.4491.2.1.28.1.2.1.2'
    OID_US_OFDMA_POWER = '1.3.6.1.4.1.4491.2.1.28.1.3.1.4'

    async def get_channel_info(self) -> Dict[str, Any]:
        """
        Get comprehensive channel info (DS/US power, frequency, modulation).
        
        Retrieves SC-QAM and OFDM/OFDMA channel information via SNMP.
        
        Returns:
            Dict with 'success', 'downstream', 'upstream' channel lists
        """
        self.logger.info(f"Getting channel info for modem {self.modem_ip}")
        
        # All OIDs to walk in parallel
        oids = [
            self.OID_DS_FREQ_CHAN,
            self.OID_DS_POWER_CHAN, 
            self.OID_DS_SNR_CHAN,
            self.OID_US_POWER_CHAN,
            self.OID_DS_OFDM_CHAN_ID,
            self.OID_DS_OFDM_SUBCARRIER_ZERO,
            self.OID_DS_OFDM_FIRST_ACTIVE,
            self.OID_DS_OFDM_LAST_ACTIVE,
            self.OID_DS_OFDM_PLC_FREQ,
            self.OID_DS_OFDM_POWER,
            self.OID_DS_OFDM_PROFILES,
            self.OID_US_OFDMA_POWER,
        ]
        
        result = await self._snmp_parallel_walk(oids)
        
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'SNMP query failed'),
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip
            }
        
        walk_results = result.get('results', {})
        
        def parse_oid_values(results_list, divisor=1):
            """Parse OID results to dict of index -> value."""
            values = {}
            for r in results_list:
                try:
                    idx = r['oid'].split('.')[-1]
                    val = r['value']
                    if isinstance(val, (int, float)):
                        values[idx] = val / divisor
                    elif isinstance(val, str) and val.lstrip('-').isdigit():
                        values[idx] = int(val) / divisor
                except:
                    pass
            return values
        
        def parse_ofdm_power_values(results_list, divisor=10):
            """Parse OFDM power with ifIndex.bandIndex format - aggregate by ifIndex."""
            values = {}
            for r in results_list:
                try:
                    oid_parts = r['oid'].split('.')
                    if_idx = oid_parts[-2]
                    val = r['value']
                    if isinstance(val, (int, float)):
                        if if_idx not in values:
                            values[if_idx] = []
                        values[if_idx].append(val / divisor)
                except:
                    pass
            return {k: sum(v)/len(v) if v else 0 for k, v in values.items()}
        
        def parse_ofdm_profiles(results_list):
            """Parse OFDM profiles BITS field."""
            profiles = {}
            for r in results_list:
                try:
                    idx = r['oid'].split('.')[-1]
                    val = r['value']
                    if isinstance(val, (bytes, list)):
                        profile_bits = val[0] if isinstance(val, list) else val[0]
                        active = [i for i in range(8) if profile_bits & (0x80 >> i)]
                        profiles[idx] = active
                    elif isinstance(val, str) and 'profile' in val.lower():
                        import re
                        profiles[idx] = [int(m) for m in re.findall(r'profile(\d+)', val.lower())]
                except:
                    pass
            return profiles
        
        # Parse all channel data
        ds_freq_map = parse_oid_values(walk_results.get(self.OID_DS_FREQ_CHAN, []))
        ds_power_map = parse_oid_values(walk_results.get(self.OID_DS_POWER_CHAN, []), 10)
        ds_snr_map = parse_oid_values(walk_results.get(self.OID_DS_SNR_CHAN, []), 10)
        us_power_map = parse_oid_values(walk_results.get(self.OID_US_POWER_CHAN, []), 10)
        
        ds_ofdm_chan_id = parse_oid_values(walk_results.get(self.OID_DS_OFDM_CHAN_ID, []))
        ds_ofdm_subcarrier_zero = parse_oid_values(walk_results.get(self.OID_DS_OFDM_SUBCARRIER_ZERO, []))
        ds_ofdm_first_active = parse_oid_values(walk_results.get(self.OID_DS_OFDM_FIRST_ACTIVE, []))
        ds_ofdm_last_active = parse_oid_values(walk_results.get(self.OID_DS_OFDM_LAST_ACTIVE, []))
        ds_ofdm_plc_freq = parse_oid_values(walk_results.get(self.OID_DS_OFDM_PLC_FREQ, []))
        ds_ofdm_power_map = parse_ofdm_power_values(walk_results.get(self.OID_DS_OFDM_POWER, []))
        ds_ofdm_profiles = parse_ofdm_profiles(walk_results.get(self.OID_DS_OFDM_PROFILES, []))
        us_ofdma_power_map = parse_oid_values(walk_results.get(self.OID_US_OFDMA_POWER, []), 10)
        
        # Build downstream list
        downstream = []
        for idx in ds_freq_map:
            downstream.append({
                'channel_id': int(idx),
                'type': 'SC-QAM',
                'frequency_mhz': ds_freq_map[idx] / 1000000,
                'power_dbmv': ds_power_map.get(idx, 0),
                'snr_db': ds_snr_map.get(idx, 0)
            })
        
        # OFDM channels
        for idx in ds_ofdm_chan_id:
            chan_id = int(ds_ofdm_chan_id.get(idx, idx))
            plc_freq = ds_ofdm_plc_freq.get(idx, 0)
            subcarrier_zero = ds_ofdm_subcarrier_zero.get(idx, 0)
            first_active = int(ds_ofdm_first_active.get(idx, 0))
            last_active = int(ds_ofdm_last_active.get(idx, 0))
            profiles = ds_ofdm_profiles.get(idx, [])
            power = ds_ofdm_power_map.get(idx, 0)
            
            downstream.append({
                'channel_id': chan_id,
                'ifindex': int(idx),
                'type': 'OFDM',
                'frequency_mhz': plc_freq / 1000000 if plc_freq else 0,
                'subcarrier_zero_freq_mhz': subcarrier_zero / 1000000 if subcarrier_zero else 0,
                'first_active_subcarrier': first_active,
                'last_active_subcarrier': last_active,
                'num_active_subcarriers': last_active - first_active + 1 if last_active >= first_active else 0,
                'power_dbmv': round(power, 1),
                'profiles': profiles,
                'current_profile': profiles[0] if profiles else None
            })
        
        # Build upstream list
        upstream = []
        for idx in us_power_map:
            upstream.append({
                'channel_id': int(idx),
                'type': 'ATDMA',
                'power_dbmv': us_power_map[idx]
            })
        
        for idx in us_ofdma_power_map:
            upstream.append({
                'channel_id': int(idx),
                'type': 'OFDMA',
                'power_dbmv': us_ofdma_power_map[idx]
            })
        
        return {
            'success': True,
            'mac_address': self.mac_address,
            'modem_ip': self.modem_ip,
            'timestamp': datetime.now().isoformat(),
            'downstream': sorted(downstream, key=lambda x: x['channel_id']),
            'upstream': sorted(upstream, key=lambda x: x['channel_id'])
        }

    # Modulation Profile OIDs (docsPnmCmDsOfdmModProfTable)
    OID_MOD_PROF_FILE_ENABLE = '1.3.6.1.4.1.4491.2.1.27.1.2.11.1.1'
    OID_MOD_PROF_MEAS_STATUS = '1.3.6.1.4.1.4491.2.1.27.1.2.11.1.2'
    OID_MOD_PROF_FILE_NAME   = '1.3.6.1.4.1.4491.2.1.27.1.2.11.1.3'

    async def trigger_modulation_profile(
        self,
        tftp_server: str = '172.22.147.18',
        channel_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Trigger DS OFDM modulation profile capture via raw SNMP.

        Flow:
          1. Set TFTP/bulk destination on modem
          2. Walk OFDM channel table to find ifIndexes
          3. For each relevant ifIndex: set filename + enable
          4. Poll status until complete or timeout
        """
        import asyncio

        self.logger.info(f"Triggering modulation profile for modem {self.modem_ip}")

        try:
            # Step 1: Set TFTP server (same bulk-destination OIDs as spectrum)
            await self._snmp_set(self.OID_BULK_IP_TYPE, 1, 'i')   # IPv4
            ip_hex = ''.join([f'{int(p):02x}' for p in tftp_server.split('.')])
            await self._snmp_set(self.OID_BULK_IP_ADDR, ip_hex, 'x')
            await self._snmp_set(self.OID_BULK_UPLOAD_CTRL, 3, 'i')  # AUTO_UPLOAD

            # Step 2: Walk OFDM channel table to discover ifIndexes
            walk_result = await self._snmp_walk(self.OID_DS_OFDM_CHAN_ID)
            ofdm_ifindexes = []
            if walk_result.get('success'):
                for entry in walk_result.get('results', []):
                    oid_str = entry.get('oid', '')
                    ifindex = int(oid_str.split('.')[-1])
                    chan_id = entry.get('value')
                    if channel_ids is None or chan_id in channel_ids:
                        ofdm_ifindexes.append(ifindex)

            if not ofdm_ifindexes:
                return {'success': False, 'error': 'No OFDM channels found on modem'}

            # Step 3: Set filename and enable for each ifIndex
            mac_clean = (self.mac_address or '').replace(':', '').lower()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filenames = {}

            for ifindex in ofdm_ifindexes:
                filename = f"modprof_{mac_clean}_{ifindex}_{timestamp}"
                filenames[ifindex] = filename
                await self._snmp_set(f"{self.OID_MOD_PROF_FILE_NAME}.{ifindex}", filename, 's')
                await self._snmp_set(f"{self.OID_MOD_PROF_FILE_ENABLE}.{ifindex}", 1, 'i')

            # Step 4: Poll status for all ifIndexes (max 60s)
            max_wait = 60
            poll_interval = 3
            elapsed = 0
            completed = set()

            while elapsed < max_wait and len(completed) < len(ofdm_ifindexes):
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                for ifindex in ofdm_ifindexes:
                    if ifindex in completed:
                        continue
                    status = await self._snmp_get(f"{self.OID_MOD_PROF_MEAS_STATUS}.{ifindex}")
                    val = None
                    if status.get('success') and status.get('output'):
                        # output is "OID = value"
                        try:
                            val = int(status['output'].split('=')[-1].strip())
                        except (ValueError, IndexError):
                            pass
                    self.logger.info(f"ModProf status ifindex={ifindex}: {val} (elapsed={elapsed}s)")
                    if val == 4:  # complete
                        completed.add(ifindex)

            return {
                'success': True,
                'mac_address': self.mac_address,
                'modem_ip': self.modem_ip,
                'timestamp': datetime.now().isoformat(),
                'channels': [
                    {'ifindex': idx, 'filename': filenames[idx], 'complete': idx in completed}
                    for idx in ofdm_ifindexes
                ],
                'filename': filenames[ofdm_ifindexes[0]] if ofdm_ifindexes else None,
            }

        except Exception as e:
            self.logger.exception(f"Modulation profile error: {e}")
            return {'success': False, 'error': str(e)}

    async def trigger_pnm_measurement(
        self,
        test_type: int,
        tftp_server: str = '172.22.147.18',
        channel_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Trigger a PNM measurement on the cable modem.

        test_type 10 (ModulationProfile) is handled directly via SNMP primitives.
        Other test types (4, 5, 8) are dispatched to the agent as named commands
        once those handlers are implemented.
        """
        self.logger.info(f"Triggering PNM measurement type {test_type} for modem {self.modem_ip}")

        if test_type == 10:
            return await self.trigger_modulation_profile(
                tftp_server=tftp_server,
                channel_ids=channel_ids
            )

        # Other test types not yet migrated to direct SNMP
        return {
            'success': False,
            'error': f'PNM test type {test_type} not yet implemented via direct SNMP'
        }



class USRxMERService:
    """
    Service for Upstream OFDMA RxMER measurements.
    
    Manages US RxMER captures on CMTS (start, status, data retrieval).
    """
    
    def __init__(self, cmts_ip: str, community: str = "public"):
        self.cmts_ip = cmts_ip
        self.community = community
        self.logger = logging.getLogger("USRxMERService")
        self.agent_manager = get_agent_manager()
    
    async def _send_agent_command(self, command: str, params: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        """Send command to agent and wait for response."""
        if not self.agent_manager:
            return {'success': False, 'error': 'Agent manager not available'}
        
        agents = self.agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available'}
        
        agent = agents[0]
        agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
        
        try:
            task_id = await self.agent_manager.send_task(
                agent_id=agent_id,
                command=command,
                params=params,
                timeout=timeout
            )
            
            result = await self.agent_manager.wait_for_task_async(task_id, timeout=timeout)
            
            if result and result.get('result'):
                return result.get('result', {})
            else:
                return {'success': False, 'error': 'Timeout or no response'}
                
        except Exception as e:
            self.logger.exception(f"Agent command error: {e}")
            return {'success': False, 'error': str(e)}

    async def start(
        self,
        ofdma_ifindex: int,
        cm_mac_address: str,
        filename: str = "us_rxmer",
        pre_eq: bool = True
    ) -> Dict[str, Any]:
        """
        Start Upstream OFDMA RxMER measurement on CMTS.
        
        Args:
            ofdma_ifindex: OFDMA channel interface index
            cm_mac_address: Cable modem MAC address
            filename: Output filename
            pre_eq: Include pre-equalization
            
        Returns:
            Dict with 'success', 'message', etc.
        """
        self.logger.info(f"Starting US RxMER for CM {cm_mac_address} on OFDMA {ofdma_ifindex}")
        
        return await self._send_agent_command(
            'pnm_us_rxmer_start',
            {
                'cmts_ip': self.cmts_ip,
                'ofdma_ifindex': ofdma_ifindex,
                'cm_mac_address': cm_mac_address,
                'community': self.community,
                'filename': filename,
                'pre_eq': pre_eq
            },
            timeout=30
        )

    async def get_status(self, ofdma_ifindex: int) -> Dict[str, Any]:
        """
        Get Upstream RxMER measurement status.
        
        Args:
            ofdma_ifindex: OFDMA channel interface index
            
        Returns:
            Dict with 'success', 'meas_status', 'is_ready', etc.
        """
        self.logger.info(f"Getting US RxMER status for OFDMA {ofdma_ifindex}")
        
        return await self._send_agent_command(
            'pnm_us_rxmer_status',
            {
                'cmts_ip': self.cmts_ip,
                'ofdma_ifindex': ofdma_ifindex,
                'community': self.community
            },
            timeout=30
        )

    async def get_data(
        self,
        ofdma_ifindex: Optional[int] = None,
        filename: str = "us_rxmer"
    ) -> Dict[str, Any]:
        """
        Fetch and parse Upstream OFDMA RxMER data.
        
        Args:
            ofdma_ifindex: OFDMA channel interface index
            filename: Capture filename
            
        Returns:
            Dict with 'success', 'data' (subcarriers, rxmer_values), etc.
        """
        self.logger.info(f"Fetching US RxMER data for {self.cmts_ip}")
        
        return await self._send_agent_command(
            'pnm_us_rxmer_data',
            {
                'cmts_ip': self.cmts_ip,
                'ofdma_ifindex': ofdma_ifindex,
                'filename': filename,
                'community': self.community
            },
            timeout=60
        )
