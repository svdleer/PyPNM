# SPDX-License-Identifier: Apache-2.0
# Async PNM Measurement Manager

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class MeasurementInfo:
    """Information about an active measurement."""
    measurement_id: str
    measurement_type: str  # "rxmer", "spectrum", "constellation", etc.
    mac_address: str
    modem_ip: str
    community: str
    started_at: datetime
    estimated_completion: datetime
    status: str  # "in_progress", "completed", "failed"
    progress: int = 0
    error: Optional[str] = None
    
    # Results
    measurements: Optional[List[Dict[str, Any]]] = None
    filename: Optional[str] = None
    completed_at: Optional[datetime] = None


class MeasurementManager:
    """Manages async PNM measurements with TFTP file polling."""
    
    def __init__(self, tftp_root: str = "/var/lib/tftpboot"):
        self.tftp_root = Path(tftp_root)
        self.active_measurements: Dict[str, MeasurementInfo] = {}
        self._polling_task: Optional[asyncio.Task] = None
        
    def start_measurement(
        self,
        measurement_type: str,
        mac_address: str,
        modem_ip: str,
        community: str,
        timeout_seconds: int = 60
    ) -> str:
        """Start a new async measurement and return measurement ID."""
        
        measurement_id = f"{measurement_type}_{mac_address.replace(':', '')}_{int(time.time())}"
        
        # Calculate expected completion time based on measurement type
        duration_map = {
            "rxmer": 35,
            "spectrum": 45,
            "constellation": 40,
            "histogram": 30,
            "channel-estimation": 35,
            "modulation-profile": 30
        }
        duration = duration_map.get(measurement_type, 45)
        
        measurement = MeasurementInfo(
            measurement_id=measurement_id,
            measurement_type=measurement_type,
            mac_address=mac_address,
            modem_ip=modem_ip,
            community=community,
            started_at=datetime.utcnow(),
            estimated_completion=datetime.utcnow() + timedelta(seconds=duration),
            status="in_progress"
        )
        
        self.active_measurements[measurement_id] = measurement
        
        # Start polling task if not running
        if not self._polling_task or self._polling_task.done():
            self._polling_task = asyncio.create_task(self._poll_tftp_files())
            
        logger.info(f"Started {measurement_type} measurement {measurement_id} for {mac_address}")
        return measurement_id
    
    def get_measurement_status(self, measurement_id: str) -> Optional[MeasurementInfo]:
        """Get current status of a measurement."""
        measurement = self.active_measurements.get(measurement_id)
        if not measurement:
            return None
            
        # Update progress based on elapsed time
        if measurement.status == "in_progress":
            elapsed = datetime.utcnow() - measurement.started_at
            total_duration = measurement.estimated_completion - measurement.started_at
            progress = min(95, int((elapsed.total_seconds() / total_duration.total_seconds()) * 100))
            measurement.progress = progress
            
        return measurement
        
    def complete_measurement(
        self, 
        measurement_id: str, 
        measurements: List[Dict[str, Any]], 
        filename: Optional[str] = None
    ):
        """Mark measurement as completed with results."""
        measurement = self.active_measurements.get(measurement_id)
        if measurement:
            measurement.status = "completed"
            measurement.progress = 100
            measurement.completed_at = datetime.utcnow()
            measurement.measurements = measurements
            measurement.filename = filename
            
            logger.info(f"Completed measurement {measurement_id} with {len(measurements)} results")
            
    def fail_measurement(self, measurement_id: str, error: str):
        """Mark measurement as failed."""
        measurement = self.active_measurements.get(measurement_id)
        if measurement:
            measurement.status = "failed"
            measurement.error = error
            measurement.completed_at = datetime.utcnow()
            
            logger.error(f"Failed measurement {measurement_id}: {error}")
    
    async def _poll_tftp_files(self):
        """Background task to poll TFTP directory for new measurement files."""
        logger.info("Started TFTP file polling")
        
        while True:
            try:
                # Check for completed measurements
                completed_ids = []
                
                for measurement_id, measurement in self.active_measurements.items():
                    if measurement.status != "in_progress":
                        continue
                        
                    # Check for timeout
                    if datetime.utcnow() > measurement.estimated_completion + timedelta(seconds=30):
                        self.fail_measurement(measurement_id, "Measurement timeout")
                        completed_ids.append(measurement_id)
                        continue
                    
                    # Look for TFTP files
                    files = self._find_measurement_files(measurement)
                    if files:
                        try:
                            parsed_data = self._parse_measurement_files(measurement, files)
                            self.complete_measurement(measurement_id, parsed_data, str(files[0]))
                            completed_ids.append(measurement_id)
                        except Exception as e:
                            logger.error(f"Error parsing measurement files for {measurement_id}: {e}")
                            self.fail_measurement(measurement_id, f"File parsing error: {e}")
                            completed_ids.append(measurement_id)
                
                # Clean up completed measurements older than 1 hour
                cutoff = datetime.utcnow() - timedelta(hours=1)
                for mid in list(self.active_measurements.keys()):
                    m = self.active_measurements[mid]
                    if m.status in ["completed", "failed"] and (m.completed_at or m.started_at) < cutoff:
                        del self.active_measurements[mid]
                        logger.debug(f"Cleaned up old measurement {mid}")
                        
            except Exception as e:
                logger.error(f"Error in TFTP polling: {e}")
                
            await asyncio.sleep(5)  # Poll every 5 seconds
            
    def _find_measurement_files(self, measurement: MeasurementInfo) -> List[Path]:
        """Find TFTP files for a measurement based on MAC and timestamp."""
        mac_clean = measurement.mac_address.replace(":", "").lower()
        start_time = int(measurement.started_at.timestamp())
        
        # Look for files created after measurement sta
        #rt
        patterns = []
        if measurement.measurement_type == "rxmer":
            patterns = [
                f"ds_ofdm_rxmer_per_subcar_{mac_clean}_*_{start_time}*.bin",
                f"{mac_clean}_{start_time}*_*_rxmer*",
                f"*rxmer*{mac_clean}*",
            ]
        elif measurement.measurement_type == "spectrum":
            patterns = [
                f"*spectrum*{mac_clean}*",
                f"{mac_clean}*spectrum*",
            ]
        # Add more patterns for other measurement types
        
        found_files = []
        for pattern in patterns:
            try:
                files = list(self.tftp_root.glob(pattern))
                # Filter by modification time (files created after measurement start)
                for file in files:
                    if file.stat().st_mtime >= start_time:
                        found_files.append(file)
            except Exception as e:
                logger.debug(f"Error searching pattern {pattern}: {e}")
                
        return found_files
        
    def _parse_measurement_files(
        self, 
        measurement: MeasurementInfo, 
        files: List[Path]
    ) -> List[Dict[str, Any]]:
        """Parse measurement files and extract data."""
        
        if measurement.measurement_type == "rxmer":
            return self._parse_rxmer_files(files)
        elif measurement.measurement_type == "spectrum":
            return self._parse_spectrum_files(files)
        # Add parsers for other measurement types
        
        return []
        
    def _parse_rxmer_files(self, files: List[Path]) -> List[Dict[str, Any]]:
        """Parse RxMER binary files."""
        measurements = []
        
        for file in files:
            try:
                # Use the actual binary RxMER parser
                from pypnm.pnm.parser.CmDsOfdmRxMer import CmDsOfdmRxMer
                
                # Read and parse the binary file
                with open(file, 'rb') as f:
                    binary_data = f.read()
                
                parser = CmDsOfdmRxMer(binary_data)
                
                # Extract actual measurements from parser
                measurements.append({
                    "channel_id": parser.channel_id,
                    "mer_db": float(parser.rxmer_stats.mean) if parser.rxmer_stats else 0.0,
                    "filename": file.name,
                    "mac_address": parser.mac_address,
                    "subcarrier_spacing_hz": parser.subcarrier_spacing,
                    "num_measurements": len(parser.rx_mer_float_data) if parser.rx_mer_float_data else 0
                })
                
                logger.info(f"Parsed RxMER file {file.name} - Channel {parser.channel_id}, Mean MER: {parser.rxmer_stats.mean:.1f} dB")
                
            except Exception as e:
                logger.error(f"Failed to parse RxMER file {file.name}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error parsing RxMER file {file}: {e}")
                
        return measurements
        
    def _parse_spectrum_files(self, files: List[Path]) -> List[Dict[str, Any]]:
        """Parse spectrum analyzer files."""
        # TODO: Implement spectrum file parsing
        return [{"message": "Spectrum data parsed", "filename": files[0].name}]


# Global measurement manager instance
_measurement_manager: Optional[MeasurementManager] = None


def get_measurement_manager() -> MeasurementManager:
    """Get or create the global measurement manager."""
    global _measurement_manager
    if _measurement_manager is None:
        _measurement_manager = MeasurementManager()
    return _measurement_manager