# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for CMTS Upstream OFDMA RxMER operations.

This module provides FastAPI endpoints for CMTS-side US OFDMA RxMER
measurements. These are CMTS-based measurements that require SNMP
access to the CMTS, not the cable modem.

Endpoints:
- POST /discover:      Discover modem's OFDMA channel ifIndex on CMTS
- POST /start:         Start US OFDMA RxMER measurement
- POST /status:        Get measurement status
- POST /destinations:  List configured bulk destinations (read-only)
- POST /getCapture:    Get and parse RxMER capture, return plot

Deprecated/removed:
- POST /destinations/create  Superseded by POST /pnm/us/bulk-destination
                             which is vendor-aware (Cisco/CommScope/Casa).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import Response

from pypnm.api.routes.pnm.us.ofdma.rxmer.schemas import (
    UsOfdmaRxMerDiscoverRequest,
    UsOfdmaRxMerDiscoverResponse,
    UsOfdmaRxMerStartRequest,
    UsOfdmaRxMerStartResponse,
    UsOfdmaRxMerStatusRequest,
    UsOfdmaRxMerStatusResponse,
    UsOfdmaRxMerCaptureRequest,
    UsOfdmaRxMerCaptureResponse,
)
from pypnm.api.routes.pnm.us.ofdma.rxmer.service import CmtsUsOfdmaRxMerService


class UsOfdmaRxMerRouter:
    """Router for CMTS Upstream OFDMA RxMER operations."""
    
    def __init__(self) -> None:
        prefix = "/pnm/us/ofdma/rxmer"
        self.router = APIRouter(
            prefix=prefix,
            tags=["PNM Operations - CMTS Upstream OFDMA RxMER"]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__routes()
    
    def __routes(self) -> None:
        
        @self.router.post(
            "/discover",
            summary="Discover modem's OFDMA channel on CMTS",
            response_model=UsOfdmaRxMerDiscoverResponse,
        )
        async def discover_ofdma(
            request: UsOfdmaRxMerDiscoverRequest
        ) -> UsOfdmaRxMerDiscoverResponse:
            """
            Discover a cable modem's OFDMA channel ifIndex on the CMTS.
            
            This endpoint queries the CMTS via SNMP to:
            1. Find the CM registration index from MAC address
            2. Find the OFDMA channel ifIndex for that CM
            3. Get the OFDMA channel description
            
            The returned ofdma_ifindex is required for starting US RxMER measurements.
            """
            self.logger.info(
                f"Discovering OFDMA for CM {request.cm_mac_address} on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.discover_modem_ofdma(request.cm_mac_address)
                return UsOfdmaRxMerDiscoverResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/start",
            summary="Start US OFDMA RxMER measurement",
            response_model=UsOfdmaRxMerStartResponse,
        )
        async def start_measurement(
            request: UsOfdmaRxMerStartRequest
        ) -> UsOfdmaRxMerStartResponse:
            """
            Start an Upstream OFDMA RxMER measurement on the CMTS.
            
            This endpoint triggers the CMTS to measure the RxMER (Receive MER)
            per subcarrier on the specified OFDMA channel for the given cable modem.
            
            The measurement runs asynchronously. Use the /status endpoint to poll
            for completion, then retrieve the results via TFTP.
            
            SNMP OIDs used (docsPnmCmtsUsOfdmaRxMerTable):
            - docsPnmCmtsUsOfdmaRxMerEnable: Start/stop measurement
            - docsPnmCmtsUsOfdmaRxMerPreEq: Pre-equalization on/off
            - docsPnmCmtsUsOfdmaRxMerNumAvgs: Number of averages
            - docsPnmCmtsUsOfdmaRxMerFileName: Output filename
            - docsPnmCmtsUsOfdmaRxMerCmMac: Target CM MAC address
            """
            self.logger.info(
                f"Starting US RxMER for CM {request.cm_mac_address}, "
                f"OFDMA ifIndex {request.ofdma_ifindex} on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.start_measurement(
                    ofdma_ifindex=request.ofdma_ifindex,
                    cm_mac=request.cm_mac_address,
                    filename=request.filename,
                    pre_eq=request.pre_eq,
                    num_averages=request.num_averages,
                    destination_index=request.destination_index,
                    tftp_server=request.tftp_server
                )
                return UsOfdmaRxMerStartResponse(**result)
            finally:
                service.close()
        
        @self.router.get(
            "/status",
            summary="Get US OFDMA RxMER measurement status",
            response_model=UsOfdmaRxMerStatusResponse,
        )
        async def get_status(
            cmts_ip: str,
            ofdma_ifindex: int,
            community: str = "public",
            write_community: Optional[str] = None
        ) -> UsOfdmaRxMerStatusResponse:
            """
            Get the status of an Upstream OFDMA RxMER measurement.

            Poll this after starting a measurement to check when it completes.
            Status: INACTIVE(2), BUSY(3), SAMPLE_READY(4), ERROR(5)
            """
            self.logger.debug(f"Getting US RxMER status for OFDMA ifIndex {ofdma_ifindex}")
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.get_status(ofdma_ifindex)
                return UsOfdmaRxMerStatusResponse(**result)
            finally:
                service.close()

        @self.router.post(
            "/getCapture",
            summary="Get and plot US OFDMA RxMER capture",
            response_model=None,
            responses={
                200: {"content": {"image/png": {}}, "description": "RxMER plot as PNG image"},
                422: {"description": "Validation error or file not found"},
            },
        )
        async def get_capture(
            request: UsOfdmaRxMerCaptureRequest
        ):
            """
            Get and parse a US OFDMA RxMER capture file, return matplotlib plot.
            
            This endpoint:
            1. Loads the capture file from the specified path
            2. Parses it using the CmtsUsOfdmaRxMer parser
            3. Generates a matplotlib bar plot of RxMER per subcarrier
            4. Returns the plot as a PNG image
            
            The file should be a PNN105 format file captured via the /start endpoint.
            """
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import numpy as np
            
            from pypnm.pnm.parser.CmtsUsOfdmaRxMer import CmtsUsOfdmaRxMer
            import glob
            
            # Build file path - CMTS adds timestamp, so use glob to find latest
            tftp_dir = Path(request.tftp_path)

            # Strip leading '/' — Cisco/E6000 SNMP returns e.g. /pnm/mer/usrxmer_xxx
            # which Python's Path join treats as absolute, discarding tftp_dir entirely.
            filename = request.filename.lstrip('/')

            # First try exact filename
            filepath = tftp_dir / filename
            
            if not filepath.exists():
                # CMTS may add a path prefix (e.g. /pnm/mer/) and/or a timestamp suffix.
                # Try in order:
                #   1. glob for timestamped variant at same relative path
                #   2. recursive search for bare filename anywhere under tftp_dir
                basename = Path(filename).name
                for pattern in [
                    str(tftp_dir / f"{filename}_*"),           # timestamped, same subdir
                    str(tftp_dir / "**" / basename),           # any subdir, exact name
                    str(tftp_dir / "**" / f"{basename}_*"),    # any subdir, timestamped
                ]:
                    matching_files = sorted(glob.glob(pattern, recursive=True), reverse=True)
                    if matching_files:
                        filepath = Path(matching_files[0])
                        self.logger.info(f"Found file via pattern '{pattern}': {filepath}")
                        break
                else:
                    self.logger.error(f"File not found: {tftp_dir / filename}")
                    return UsOfdmaRxMerCaptureResponse(
                        success=False,
                        error=f"File not found: {tftp_dir / basename}"
                    )
            
            self.logger.info(f"Loading US RxMER file: {filepath}")
            
            try:
                # Read and parse file
                data = filepath.read_bytes()
                parser = CmtsUsOfdmaRxMer(data)
                model = parser.to_model()
                
                # Get RxMER values
                values = model.values
                valid_values = [v for v in values if v < 63.5]  # Filter excluded subcarriers
                
                # Calculate frequencies for x-axis
                spacing_khz = model.subcarrier_spacing / 1000
                zero_freq_mhz = model.subcarrier_zero_frequency / 1e6
                first_idx = model.first_active_subcarrier_index
                
                # Create frequency array in MHz
                freqs_mhz = [
                    zero_freq_mhz + (first_idx + i) * spacing_khz / 1000
                    for i in range(len(values))
                ]
                
                # Create matplotlib figure - match DS RxMER style
                fig, ax = plt.subplots(figsize=(14, 6))
                
                # Line plot with same blue color as DS RxMER
                line_color = '#36A2EB'  # rgb(54, 162, 235)
                fill_color = 'rgba(54, 162, 235, 0.2)'
                
                # Plot line with fill
                ax.plot(freqs_mhz, values, color=line_color, linewidth=1.5, label='RxMER')
                ax.fill_between(freqs_mhz, values, alpha=0.2, color=line_color)
                
                # Add threshold lines matching DS RxMER style
                ax.axhline(y=35, color='#4CAF50', linestyle='--', alpha=0.7, linewidth=1, label='Good (≥35 dB)')
                ax.axhline(y=30, color='#FF9800', linestyle='--', alpha=0.7, linewidth=1, label='Marginal (≥30 dB)')
                
                # Labels and title
                preeq_label = "Pre-EQ: ON" if model.preeq_enabled else "Pre-EQ: OFF"
                ax.set_xlabel('Frequency (MHz)', fontsize=12)
                ax.set_ylabel('RxMER (dB)', fontsize=12)
                ax.set_title(
                    f'Upstream OFDMA RxMER - CM: {model.cm_mac_address}\n'
                    f'CCAP: {model.ccap_id} | {preeq_label} | '
                    f'Avg: {model.signal_statistics.mean:.1f} dB | '
                    f'Min: {min(valid_values):.1f} dB | '
                    f'Max: {max(valid_values):.1f} dB | '
                    f'Subcarriers: {model.num_active_subcarriers}',
                    fontsize=11
                )
                
                # Set y-axis limits with auto-scaling based on data
                y_min = min(valid_values)
                y_max = max(valid_values)
                y_range = y_max - y_min
                y_padding = max(2.0, y_range * 0.1)  # At least 2dB padding or 10% of range
                ax.set_ylim(max(0, y_min - y_padding), y_max + y_padding)
                ax.set_xlim(min(freqs_mhz) - 0.2, max(freqs_mhz) + 0.2)
                
                # Grid and legend
                ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
                ax.legend(loc='lower right', fontsize=9)
                
                plt.tight_layout()
                
                # Save to bytes buffer
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                plt.close(fig)
                buf.seek(0)
                
                return Response(
                    content=buf.getvalue(),
                    media_type="image/png",
                    headers={
                        "Content-Disposition": f"inline; filename=us_rxmer_{model.cm_mac_address.replace(':', '')}.png"
                    }
                )
                
            except Exception as e:
                self.logger.error(f"Error parsing US RxMER file: {e}")
                return UsOfdmaRxMerCaptureResponse(
                    success=False,
                    error=str(e)
                )

        @self.router.post(
            "/getData",
            summary="Get parsed US OFDMA RxMER capture as JSON",
            response_model=UsOfdmaRxMerCaptureResponse,
        )
        async def get_data(
            request: UsOfdmaRxMerCaptureRequest
        ) -> UsOfdmaRxMerCaptureResponse:
            """
            Parse a US OFDMA RxMER capture file and return raw data as JSON.
            Same file resolution logic as /getCapture, but returns parsed values instead of PNG.
            """
            from pypnm.pnm.parser.CmtsUsOfdmaRxMer import CmtsUsOfdmaRxMer
            import glob

            tftp_dir = Path(request.tftp_path)
            filename = request.filename.lstrip('/')
            filepath = tftp_dir / filename

            if not filepath.exists():
                basename = Path(filename).name
                for pattern in [
                    str(tftp_dir / f"{filename}_*"),
                    str(tftp_dir / "**" / basename),
                    str(tftp_dir / "**" / f"{basename}_*"),
                ]:
                    matching_files = sorted(glob.glob(pattern, recursive=True), reverse=True)
                    if matching_files:
                        filepath = Path(matching_files[0])
                        break
                else:
                    return UsOfdmaRxMerCaptureResponse(
                        success=False,
                        error=f"File not found: {tftp_dir / Path(filename).name}"
                    )

            try:
                data = filepath.read_bytes()
                parser = CmtsUsOfdmaRxMer(data)
                model = parser.to_model()

                values = model.values
                spacing_khz = model.subcarrier_spacing / 1000
                zero_freq_mhz = model.subcarrier_zero_frequency / 1e6
                first_idx = model.first_active_subcarrier_index
                freqs_mhz = [
                    round(zero_freq_mhz + (first_idx + i) * spacing_khz / 1000, 4)
                    for i in range(len(values))
                ]

                stats = model.signal_statistics
                valid = [v for v in values if v < 63.5]

                return UsOfdmaRxMerCaptureResponse(
                    success=True,
                    cm_mac_address=model.cm_mac_address,
                    ccap_id=model.ccap_id,
                    num_active_subcarriers=model.num_active_subcarriers,
                    first_active_subcarrier_index=model.first_active_subcarrier_index,
                    subcarrier_zero_frequency_hz=model.subcarrier_zero_frequency,
                    subcarrier_spacing_hz=model.subcarrier_spacing,
                    num_averages=getattr(model, 'num_averages', None),
                    preeq_enabled=model.preeq_enabled,
                    rxmer_min_db=round(min(valid), 2) if valid else None,
                    rxmer_avg_db=round(stats.mean, 2),
                    rxmer_max_db=round(max(valid), 2) if valid else None,
                    rxmer_std_db=round(stats.std, 2) if hasattr(stats, 'std') else None,
                    values=[round(v, 2) for v in values],
                    frequencies_mhz=freqs_mhz,
                )
            except Exception as e:
                self.logger.error(f"Error parsing US RxMER file for getData: {e}")
                return UsOfdmaRxMerCaptureResponse(success=False, error=str(e))


# Required for dynamic auto-registration
router = UsOfdmaRxMerRouter().router
