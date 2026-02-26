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
    UsOfdmaRxMerComparisonRequest,
    FiberNodeAnalysisRequest,
    FiberNodeAnalysis,
    FiberNodeCaptureEntry,
    RxMerCapture,
    SubcarrierGroupStats,
    ModemAssessment,
    FiberNodeSummary,
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
                    filename=str(filepath.name),
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

        # ------------------------------------------------------------------
        # Shared analysis engine (used by all comparison + fiber node routes)
        # ------------------------------------------------------------------

        def _load_rxmer_capture(filename: str, tftp_path: str, preeq_enabled: bool, cm_mac: str = None) -> RxMerCapture:
            """Parse one RxMER file into a RxMerCapture model."""
            from pypnm.pnm.parser.CmtsUsOfdmaRxMer import CmtsUsOfdmaRxMer
            import glob, statistics as _stat

            tftp_dir = Path(tftp_path)
            fn = filename.lstrip('/')
            fp = tftp_dir / fn
            if not fp.exists():
                basename = Path(fn).name
                for pat in [
                    str(tftp_dir / f"{fn}_*"),
                    str(tftp_dir / "**" / basename),
                    str(tftp_dir / "**" / f"{basename}_*"),
                ]:
                    matches = sorted(glob.glob(pat, recursive=True), reverse=True)
                    if matches:
                        fp = Path(matches[0])
                        break
                else:
                    raise FileNotFoundError(f"File not found: {Path(fn).name}")

            model = CmtsUsOfdmaRxMer(fp.read_bytes()).to_model()
            vals = model.values
            spacing_khz = model.subcarrier_spacing / 1000
            zero_mhz = model.subcarrier_zero_frequency / 1e6
            first_idx = model.first_active_subcarrier_index
            freqs = [round(zero_mhz + (first_idx + i) * spacing_khz / 1000, 4) for i in range(len(vals))]
            valid = [v for v in vals if v < 63.5]
            stats = model.signal_statistics
            std = round(_stat.stdev(valid), 2) if len(valid) > 1 else 0.0
            return RxMerCapture(
                cm_mac_address=cm_mac or model.cm_mac_address,
                preeq_enabled=preeq_enabled,
                filename=str(fp.name),
                values=[round(v, 2) for v in vals],
                frequencies_mhz=freqs,
                rxmer_avg_db=round(stats.mean, 2),
                rxmer_min_db=round(min(valid), 2) if valid else None,
                rxmer_max_db=round(max(valid), 2) if valid else None,
                rxmer_std_db=std,
            )

        def _analyze(captures: list) -> FiberNodeAnalysis:
            """
            Core analysis engine — works for any number of captures.
            Groups by MAC for pre-eq pairing; aligns subcarriers; computes
            per-subcarrier group stats and per-modem assessments.
            """
            import statistics as _stat

            if not captures:
                return FiberNodeAnalysis(success=False, error="No captures provided")

            # Align all captures to shortest subcarrier count
            n = min(len(c.values) for c in captures)
            freqs = captures[0].frequencies_mhz[:n]

            # Per-subcarrier group stats (exclude 0xff = 63.75 markers)
            subcarrier_stats: list[SubcarrierGroupStats] = []
            for i in range(n):
                sc_vals = [c.values[i] for c in captures if c.values[i] < 63.5]
                if not sc_vals:
                    sc_vals = [0.0]
                mean = round(_stat.mean(sc_vals), 2)
                std  = round(_stat.stdev(sc_vals), 2) if len(sc_vals) > 1 else 0.0
                sorted_v = sorted(sc_vals)
                p10 = round(sorted_v[max(0, int(len(sorted_v) * 0.10))], 2)
                p90 = round(sorted_v[min(len(sorted_v) - 1, int(len(sorted_v) * 0.90))], 2)
                outlier_macs = [
                    c.cm_mac_address for c in captures
                    if c.values[i] < 63.5 and c.values[i] < mean - 2 * std
                ]
                subcarrier_stats.append(SubcarrierGroupStats(
                    frequency_mhz=freqs[i] if i < len(freqs) else i,
                    index=i,
                    values_db=[round(c.values[i], 2) for c in captures],
                    mean_db=mean, std_db=std,
                    min_db=round(min(sc_vals), 2), max_db=round(max(sc_vals), 2),
                    p10_db=p10, p90_db=p90,
                    outlier_macs=outlier_macs,
                ))

            # Group captures by MAC for pre-eq pairing
            by_mac: dict[str, list] = {}
            for c in captures:
                by_mac.setdefault(c.cm_mac_address, []).append(c)

            # Global group average across all captures
            all_avgs = [c.rxmer_avg_db for c in captures if c.rxmer_avg_db is not None]
            group_avg = round(_stat.mean(all_avgs), 2) if all_avgs else 0.0
            group_std = round(_stat.stdev(all_avgs), 2) if len(all_avgs) > 1 else 0.0

            # Subcarriers bad on >50% of all captures
            num_caps = len(captures)
            shared_bad_idxs = {
                i for i, ss in enumerate(subcarrier_stats)
                if len(ss.outlier_macs) > num_caps * 0.5
            }
            network_freqs = [subcarrier_stats[i].frequency_mhz for i in shared_bad_idxs]

            modem_assessments: list[ModemAssessment] = []
            for mac, mac_captures in by_mac.items():
                # Split by pre-eq flag
                on_list  = [c for c in mac_captures if c.preeq_enabled]
                off_list = [c for c in mac_captures if not c.preeq_enabled]
                # Representative capture: prefer preeq_on, else first
                rep = on_list[0] if on_list else mac_captures[0]

                mac_avg = rep.rxmer_avg_db or 0.0
                delta_from_group = round(mac_avg - group_avg, 2)

                # How many subcarriers is this MAC an outlier on?
                mac_outlier_count = sum(1 for ss in subcarrier_stats if mac in ss.outlier_macs)
                outlier_score = round(mac_outlier_count / n, 3) if n > 0 else 0.0

                # Unique vs shared bad subcarriers
                mac_bad_idxs = {i for i, ss in enumerate(subcarrier_stats) if mac in ss.outlier_macs}
                unique_bad = len(mac_bad_idxs - shared_bad_idxs)
                shared_bad = len(mac_bad_idxs & shared_bad_idxs)

                # Multi-modem group assessment
                if num_caps > 1:
                    if unique_bad > shared_bad and outlier_score > 0.15:
                        assessment = "in-home"
                    elif len(shared_bad_idxs) > n * 0.3:
                        assessment = "network"
                    elif outlier_score < 0.05:
                        assessment = "clean"
                    else:
                        assessment = "inconclusive"
                else:
                    assessment = "clean" if mac_avg >= 35 else ("outlier" if mac_avg < 28 else "inconclusive")

                # Pre-eq comparison (ON vs OFF for same MAC)
                preeq_delta_avg = preeq_num_improved = preeq_assessment = None
                if on_list and off_list:
                    vals_on  = on_list[0].values[:n]
                    vals_off = off_list[0].values[:n]
                    delta_vals = [vals_on[i] - vals_off[i] for i in range(n)
                                  if vals_on[i] < 63.5 and vals_off[i] < 63.5]
                    if delta_vals:
                        preeq_delta_avg = round(_stat.mean(delta_vals), 2)
                        preeq_num_improved = sum(1 for d in delta_vals if d > 0.5)
                        pct_improved = preeq_num_improved / len(delta_vals)
                        if preeq_delta_avg > 2.0 and pct_improved > 0.5:
                            preeq_assessment = "in-home"
                        elif preeq_delta_avg < -1.0:
                            preeq_assessment = "network"
                        elif abs(preeq_delta_avg) <= 1.0:
                            preeq_assessment = "clean"
                        else:
                            preeq_assessment = "inconclusive"
                        # Override group assessment with pre-eq result when available
                        if num_caps <= 2:
                            assessment = preeq_assessment or assessment

                modem_assessments.append(ModemAssessment(
                    cm_mac_address=mac,
                    preeq_enabled=rep.preeq_enabled,
                    rxmer_avg_db=mac_avg,
                    delta_from_group_avg_db=delta_from_group,
                    unique_bad_subcarriers=unique_bad,
                    shared_bad_subcarriers=shared_bad,
                    outlier_score=outlier_score,
                    assessment=assessment,
                    preeq_delta_avg_db=preeq_delta_avg,
                    preeq_num_improved=preeq_num_improved,
                    preeq_assessment=preeq_assessment,
                ))

            worst = min(modem_assessments, key=lambda m: m.rxmer_avg_db) if modem_assessments else None
            pct_ih = round(sum(1 for m in modem_assessments if m.assessment == "in-home") / max(len(modem_assessments), 1) * 100, 1)
            summary = FiberNodeSummary(
                num_captures=len(captures),
                num_modems=len(by_mac),
                group_avg_db=group_avg,
                group_std_db=group_std,
                pct_network_impaired=round(len(shared_bad_idxs) / max(n, 1) * 100, 1),
                network_impaired_frequencies_mhz=sorted(network_freqs),
                pct_modems_in_home=pct_ih,
                worst_modem_mac=worst.cm_mac_address if worst else None,
                worst_modem_delta_db=worst.delta_from_group_avg_db if worst else None,
            )
            return FiberNodeAnalysis(
                success=True,
                captures=captures,
                subcarrier_stats=subcarrier_stats,
                modem_assessments=modem_assessments,
                summary=summary,
            )

        def _plot_analysis(analysis: FiberNodeAnalysis) -> bytes:
            """Generate overlay PNG from a FiberNodeAnalysis."""
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.cm as mcm

            captures = analysis.captures
            n_plots = len(captures)
            colors = [mcm.tab10(i / max(n_plots, 1)) for i in range(n_plots)]

            # Two panels: top = RxMER traces; bottom = per-subcarrier mean ± std or delta
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True,
                                           gridspec_kw={'height_ratios': [3, 1]})

            for i, cap in enumerate(captures):
                n = min(len(cap.values), len(cap.frequencies_mhz))
                label = f"{cap.cm_mac_address} Pre-EQ={'ON' if cap.preeq_enabled else 'OFF'}"
                ax1.plot(cap.frequencies_mhz[:n], cap.values[:n],
                         color=colors[i], linewidth=1.2, alpha=0.85, label=label)

            ax1.axhline(y=35, color='#4CAF50', linestyle='--', alpha=0.6, linewidth=1, label='Good (≥35 dB)')
            ax1.axhline(y=30, color='#F44336', linestyle='--', alpha=0.6, linewidth=1, label='Marginal (≥30 dB)')
            ax1.set_ylabel('RxMER (dB)', fontsize=11)
            ax1.grid(True, alpha=0.3)
            ax1.legend(loc='lower right', fontsize=8, ncol=min(n_plots + 2, 4))

            # Build title from assessments
            summary = analysis.summary
            title_lines = [f"US OFDMA RxMER — {summary.num_modems} modem(s), {summary.num_captures} capture(s)"]
            for ma in analysis.modem_assessments:
                parts = [f"{ma.cm_mac_address}: {ma.rxmer_avg_db:.1f} dB avg → {ma.assessment.upper()}"]
                if ma.preeq_assessment:
                    parts.append(f"(pre-eq: {ma.preeq_assessment}, Δ={ma.preeq_delta_avg_db:+.1f} dB)")
                title_lines.append("  " + " ".join(parts))
            ax1.set_title("\n".join(title_lines), fontsize=10)

            # Bottom panel: if ≥2 captures with same MAC and both preeq flags → delta bar
            # otherwise group mean ± 1σ
            ss = analysis.subcarrier_stats
            if ss:
                freqs_ss = [s.frequency_mhz for s in ss]
                means    = [s.mean_db for s in ss]
                stds     = [s.std_db for s in ss]
                bar_w = (freqs_ss[1] - freqs_ss[0]) if len(freqs_ss) > 1 else 0.05

                # Check for pre-eq delta
                preeq_pairs = [(ma.preeq_delta_avg_db, ma.cm_mac_address)
                               for ma in analysis.modem_assessments if ma.preeq_delta_avg_db is not None]
                if preeq_pairs and len(captures) == 2:
                    n_sc = min(len(captures[0].values), len(captures[1].values), len(ss))
                    deltas = [captures[0].values[i] - captures[1].values[i] for i in range(n_sc)]
                    bar_colors = ['#4CAF50' if d > 0 else '#F44336' for d in deltas]
                    ax2.bar(freqs_ss[:n_sc], deltas, width=bar_w, color=bar_colors, alpha=0.7)
                    ax2.axhline(y=0, color='black', linewidth=0.8)
                    ax2.set_ylabel('Δ RxMER (dB)\n(ON−OFF)', fontsize=9)
                    ax2.set_title('Pre-EQ delta: green = pre-eq improves, red = degrades', fontsize=9)
                else:
                    ax2.plot(freqs_ss, means, color='#36A2EB', linewidth=1.5, label='Group mean')
                    ax2.fill_between(freqs_ss,
                                     [m - s for m, s in zip(means, stds)],
                                     [m + s for m, s in zip(means, stds)],
                                     alpha=0.2, color='#36A2EB', label='±1σ')
                    ax2.set_ylabel('Group RxMER (dB)', fontsize=9)
                    ax2.set_title('Per-subcarrier group statistics', fontsize=9)
                    ax2.legend(fontsize=8)

            ax2.set_xlabel('Frequency (MHz)', fontsize=11)
            ax2.grid(True, alpha=0.3)

            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return buf.getvalue()

        # ------------------------------------------------------------------
        # /getComparisonData  (2-capture pre-eq convenience wrapper)
        # ------------------------------------------------------------------

        @self.router.post(
            "/getComparisonData",
            summary="Compare pre-eq ON vs OFF as JSON (FiberNodeAnalysis)",
            response_model=FiberNodeAnalysis,
        )
        async def get_comparison_data(
            request: UsOfdmaRxMerComparisonRequest
        ) -> FiberNodeAnalysis:
            """Convenience wrapper: two captures (pre-eq ON/OFF) → FiberNodeAnalysis."""
            try:
                cap_on  = _load_rxmer_capture(request.filename_preeq_on,  request.tftp_path, True)
                cap_off = _load_rxmer_capture(request.filename_preeq_off, request.tftp_path, False,
                                              cm_mac=cap_on.cm_mac_address)
                return _analyze([cap_on, cap_off])
            except Exception as e:
                self.logger.error(f"getComparisonData error: {e}")
                return FiberNodeAnalysis(success=False, error=str(e))

        # ------------------------------------------------------------------
        # /getComparison  (2-capture pre-eq overlay PNG)
        # ------------------------------------------------------------------

        @self.router.post(
            "/getComparison",
            summary="Compare pre-eq ON vs OFF as overlay PNG",
            response_model=None,
            responses={200: {"content": {"image/png": {}}}},
        )
        async def get_comparison(request: UsOfdmaRxMerComparisonRequest):
            """Convenience wrapper: two captures (pre-eq ON/OFF) → overlay PNG."""
            try:
                cap_on  = _load_rxmer_capture(request.filename_preeq_on,  request.tftp_path, True)
                cap_off = _load_rxmer_capture(request.filename_preeq_off, request.tftp_path, False,
                                              cm_mac=cap_on.cm_mac_address)
                analysis = _analyze([cap_on, cap_off])
                return Response(content=_plot_analysis(analysis), media_type="image/png",
                                headers={"Content-Disposition": "inline; filename=us_rxmer_comparison.png"})
            except Exception as e:
                self.logger.error(f"getComparison error: {e}")
                return UsOfdmaRxMerCaptureResponse(success=False, error=str(e))

        # ------------------------------------------------------------------
        # /fiberNode/analyze  — unified multi-modem JSON
        # ------------------------------------------------------------------

        @self.router.post(
            "/fiberNode/analyze",
            summary="Fiber node group RxMER analysis (JSON)",
            response_model=FiberNodeAnalysis,
        )
        async def fiber_node_analyze(request: FiberNodeAnalysisRequest) -> FiberNodeAnalysis:
            """
            Analyze N RxMER captures across multiple modems on the same fiber node.

            - Groups captures by cm_mac_address
            - Computes per-subcarrier group statistics (mean, std, p10, p90)
            - Assesses each modem: in-home / network / clean / outlier
            - If a modem has both preeq_enabled=true and false captures, computes pre-eq delta
            - Single modem + both preeq flags → same as /getComparisonData
            """
            try:
                captures = [
                    _load_rxmer_capture(e.filename, request.tftp_path, e.preeq_enabled, e.cm_mac_address)
                    for e in request.captures
                ]
                return _analyze(captures)
            except Exception as e:
                self.logger.error(f"fiberNode/analyze error: {e}")
                return FiberNodeAnalysis(success=False, error=str(e))

        # ------------------------------------------------------------------
        # /fiberNode/plot  — unified multi-modem overlay PNG
        # ------------------------------------------------------------------

        @self.router.post(
            "/fiberNode/plot",
            summary="Fiber node group RxMER analysis (overlay PNG)",
            response_model=None,
            responses={200: {"content": {"image/png": {}}}},
        )
        async def fiber_node_plot(request: FiberNodeAnalysisRequest):
            """Same as /fiberNode/analyze but returns a matplotlib overlay PNG."""
            try:
                captures = [
                    _load_rxmer_capture(e.filename, request.tftp_path, e.preeq_enabled, e.cm_mac_address)
                    for e in request.captures
                ]
                analysis = _analyze(captures)
                return Response(content=_plot_analysis(analysis), media_type="image/png",
                                headers={"Content-Disposition": "inline; filename=us_rxmer_fibernode.png"})
            except Exception as e:
                self.logger.error(f"fiberNode/plot error: {e}")
                return UsOfdmaRxMerCaptureResponse(success=False, error=str(e))

        # ------------------------------------------------------------------
        # DOCS-IF3-MIB fiber node name resolution
        #
        # Verified OIDs (1.3.6.1.4.1.4491.2.1.20 = docsIf3Mib):
        #   docsIf3MdChCfgChId        .1.5.1.3  (mdIfIndex, chIfIndex) → chId
        #   docsIf3UsChSetChList       .1.22.1.2 (mdIfIndex, chSetId)   → HEX bytes of chIds
        #   docsIf3MdUsSgStatusChSetId .1.14.1.2 (mdIfIndex, mUSsgId)  → chSetId
        #   docsIf3MdNodeStatusMdUsSgId.1.12.1.4 (mdIfIndex, strLen, chars..., mCmSgId) → mUSsgId
        #     FN name extracted from OID index: strLen + char bytes
        # ------------------------------------------------------------------

        async def _resolve_fn_names(svc, ofdma_ifindex_set: set) -> dict:
            """
            Resolve real FN names from DOCS-IF3-MIB for all vendors.
            Returns {chIfIndex: fnName} or {} when tables are unavailable.
            """
            BASE = "1.3.6.1.4.1.4491.2.1.20"
            OID_CHID   = f"{BASE}.1.5.1.3"   # docsIf3MdChCfgChId
            OID_CHLIST = f"{BASE}.1.22.1.2"  # docsIf3UsChSetChList  (Hex-STRING)
            OID_SGSET  = f"{BASE}.1.14.1.2"  # docsIf3MdUsSgStatusChSetId
            OID_FNSG   = f"{BASE}.1.12.1.4"  # docsIf3MdNodeStatusMdUsSgId (col 4)

            def _to_dict(walk_result):
                if not isinstance(walk_result, dict) or not walk_result.get('success'):
                    return None
                raw = walk_result.get('results') or []
                return {item['oid']: item['value']
                        for item in raw if isinstance(item, dict) and 'oid' in item}

            # ── Step 1: (mdIfIndex, chIfIndex) → chId ──────────────────────
            w1 = await svc._snmp_walk(OID_CHID, timeout=30)
            d1 = _to_dict(w1)
            if not d1:
                return {}

            ifidx_to_md_chid: dict = {}   # chIfIndex → (mdIfIndex, chId)
            pfx1 = OID_CHID + "."
            for oid, val in d1.items():
                if not oid.startswith(pfx1):
                    continue
                parts = oid[len(pfx1):].split('.')
                if len(parts) != 2:
                    continue
                md_if = int(parts[0]);  ch_if = int(parts[1])
                if ch_if in ofdma_ifindex_set:
                    ifidx_to_md_chid[ch_if] = (md_if, int(str(val).strip()))

            if not ifidx_to_md_chid:
                return {}

            # ── Step 2: (mdIfIndex, chSetId) → frozenset of chIds ──────────
            # Value is Hex-STRING: each byte is one chId
            w2 = await svc._snmp_walk(OID_CHLIST, timeout=30)
            d2 = _to_dict(w2)
            if not d2:
                return {}

            chset_chids: dict = {}   # (mdIfIndex, chSetId) → frozenset of chIds
            pfx2 = OID_CHLIST + "."
            for oid, val in d2.items():
                if not oid.startswith(pfx2):
                    continue
                parts = oid[len(pfx2):].split('.')
                if len(parts) != 2:
                    continue
                md_if = int(parts[0]);  chset_id = int(parts[1])
                # val may come as "0x01 02 03..." hex string or plain bytes
                s = str(val).strip()
                if s.startswith('0x') or ' ' in s:
                    # Hex-STRING from SNMP agent: "01 02 03 04 19 1A"
                    try:
                        chids = frozenset(int(b, 16) for b in s.replace('0x','').split())
                    except ValueError:
                        continue
                else:
                    # Fallback: comma-separated integers
                    try:
                        chids = frozenset(int(x) for x in s.split(',') if x.strip().isdigit())
                    except ValueError:
                        continue
                chset_chids[(md_if, chset_id)] = chids

            # ── Step 3: (mdIfIndex, mUSsgId) → chSetId ─────────────────────
            w3 = await svc._snmp_walk(OID_SGSET, timeout=30)
            d3 = _to_dict(w3)
            if not d3:
                return {}

            # Build: (mdIfIndex, chSetId) → mUSsgId  (reverse of table)
            chset_to_ussg: dict = {}
            pfx3 = OID_SGSET + "."
            for oid, val in d3.items():
                if not oid.startswith(pfx3):
                    continue
                parts = oid[len(pfx3):].split('.')
                if len(parts) != 2:
                    continue
                md_if = int(parts[0]);  m_us_sg = int(parts[1])
                chset_id = int(str(val).strip())
                chset_to_ussg[(md_if, chset_id)] = m_us_sg

            # ── Step 4: decode FN name from OID index of .1.12.1.4 ─────────
            # OID suffix: {mdIfIndex}.{strLen}.{byte0}...{byteN-1}.{mCmSgId} = mUSsgId
            w4 = await svc._snmp_walk(OID_FNSG, timeout=30)
            d4 = _to_dict(w4)
            if not d4:
                return {}

            ussg_to_fn: dict = {}   # (mdIfIndex, mUSsgId) → fnName (first wins)
            pfx4 = OID_FNSG + "."
            for oid, val in d4.items():
                if not oid.startswith(pfx4):
                    continue
                parts = oid[len(pfx4):].split('.')
                if len(parts) < 3:
                    continue
                md_if   = int(parts[0])
                str_len = int(parts[1])
                if len(parts) < 2 + str_len + 1:
                    continue
                fn_name = ''.join(chr(int(b)) for b in parts[2:2 + str_len])
                m_us_sg = int(str(val).strip())
                ussg_to_fn.setdefault((md_if, m_us_sg), fn_name)

            # ── Compose: chIfIndex → fnName ─────────────────────────────────
            result: dict = {}
            for ch_if, (md_if, ch_id) in ifidx_to_md_chid.items():
                for (md2, chset_id), chids in chset_chids.items():
                    if md2 != md_if:
                        continue
                    if ch_id not in chids:
                        continue
                    m_us_sg = chset_to_ussg.get((md_if, chset_id))
                    if m_us_sg is None:
                        continue
                    fn_name = ussg_to_fn.get((md_if, m_us_sg))
                    if fn_name:
                        result[ch_if] = fn_name
                    break
            return result

        @self.router.get(
            "/channel/list",
            summary="List all OFDMA upstream channels on a CMTS",
        )
        async def get_channel_list(
            cmts_ip: str,
            community: str = "public",
        ):
            """
            Walk ifDescr + DOCS-IF3-MIB fiber node tables to return all OFDMA
            upstream interfaces grouped by real fiber node name.
            Falls back to ifDescr-derived grouping when DOCS-IF3-MIB tables
            are unavailable (non-standard vendors).
            """
            import re as _re
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=cmts_ip, community=community, write_community=community
            )
            try:
                OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
                walk = await service._snmp_walk(OID_IF_DESCR, timeout=30)
                if not isinstance(walk, dict) or not walk.get('success'):
                    return {"success": False, "error": walk.get('error', 'SNMP walk failed'), "channels": [], "fiber_nodes": []}

                # agent returns {'results': [{oid, value, type}, ...]}
                raw = walk.get('results') or []
                if isinstance(raw, list):
                    oid_map = {item['oid']: item['value'] for item in raw if isinstance(item, dict) and 'oid' in item}
                elif isinstance(raw, dict):
                    oid_map = raw
                else:
                    oid_map = {}

                channels = []
                for oid, raw_val in oid_map.items():
                    desc = str(raw_val).strip().strip('"')
                    lower = desc.lower()
                    # Vendor OFDMA detection (SC-QAM variants are excluded):
                    # Commscope OFDMA:  "cable-us-ofdma 1/ofd/32.0"
                    # Commscope SC-QAM: "cable-upstream 1/scq/7", "1/nd/7", "1/0/7" → excluded (no 'us-ofdma')
                    # Cisco OFDMA:      "Cable1/0/0-upstream0"  (capital C + hyphen-upstream)
                    # Casa OFDMA:       "Logical Upstream Channel 0/0.0-0"
                    # Casa SC-QAM:      "Upstream Physical Interface 0/0.0" → excluded
                    is_commscope_ofdma = 'us-ofdma' in lower
                    is_cisco_ofdma     = desc.startswith('Cable') and '-upstream' in lower
                    is_casa_ofdma      = lower.startswith('logical') and 'upstream' in lower
                    if not (is_commscope_ofdma or is_cisco_ofdma or is_casa_ofdma):
                        continue
                    try:
                        ifindex = int(str(oid).rsplit('.', 1)[-1])
                    except ValueError:
                        continue
                    # Fallback MAC-domain grouping (used when DOCS-IF3-MIB unavailable):
                    # Commscope: "cable-us-ofdma 1/ofd/32.0" → "cable-mac 1"
                    # Cisco:     "Cable1/0/0-upstream0"        → "Cable1/0/0"
                    # Casa:      "Logical Upstream Channel 0/0.0-0" → "LogicalUS-0/0"
                    m_arris = _re.match(r'cable-us-ofdma\s+(\d+)/', desc, _re.IGNORECASE)
                    m_casa  = _re.match(r'Logical\s+Upstream\s+Channel\s+(\d+/\d+)', desc, _re.IGNORECASE)
                    if m_arris:
                        fallback_md = f"cable-mac {m_arris.group(1)}"
                    elif m_casa:
                        fallback_md = f"LogicalUS-{m_casa.group(1)}"
                    elif _re.search(r'[-_]upstream', desc, _re.IGNORECASE):
                        fallback_md = _re.split(r'[-_]upstream', desc, flags=_re.IGNORECASE)[0].strip()
                    else:
                        fallback_md = desc
                    channels.append({
                        "ifindex":      ifindex,
                        "description":  desc,
                        "mac_domain":   fallback_md,
                        "suggested_fn": "FN-" + fallback_md.replace('/', '-').replace(' ', '-').strip('-'),
                    })

                if not channels:
                    return {"success": True, "channels": [], "fiber_nodes": []}

                # ── Try DOCS-IF3-MIB fiber node resolution ──────────────────
                ofdma_set = {ch['ifindex'] for ch in channels}
                try:
                    fn_map = await _resolve_fn_names(service, ofdma_set)
                except Exception as _fn_err:
                    self.logger.warning(f"FN resolution failed, using fallback: {_fn_err}")
                    fn_map = {}

                # Apply real FN names where available
                for ch in channels:
                    real_fn = fn_map.get(ch['ifindex'])
                    if real_fn:
                        ch['mac_domain']   = real_fn
                        ch['suggested_fn'] = real_fn

                channels.sort(key=lambda c: c['description'])
                seen: dict = {}
                for ch in channels:
                    md = ch['mac_domain']
                    if md not in seen:
                        seen[md] = {"name": ch['suggested_fn'], "mac_domain": md, "channels": []}
                    seen[md]['channels'].append({"ifindex": ch['ifindex'], "description": ch['description']})

                return {
                    "success":     True,
                    "channels":    channels,
                    "fiber_nodes": sorted(seen.values(), key=lambda f: f['mac_domain']),
                }
            except Exception as e:
                self.logger.error(f"channel/list error: {e}")
                return {"success": False, "error": str(e), "channels": [], "fiber_nodes": []}
            finally:
                service.close()

        @self.router.get(
            "/channel/modems",
            summary="List modems registered on an OFDMA upstream channel",
        )
        async def get_channel_modems(
            cmts_ip: str,
            ofdma_ifindex: int,
            community: str = "public",
            max_modems: int = 50,
        ):
            """
            Walk docsIf3CmtsCmUsStatusTable (.1) to find all CMs on a given
            OFDMA upstream ifIndex, then get their MAC from
            docsIf3CmtsCmRegStatusMacAddr (.3).
            Returns [{cm_mac_address, cm_index}].
            """
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=cmts_ip, community=community, write_community=community
            )
            try:
                # docsIf3CmtsCmUsStatusChIfIndex  1.3.6.1.4.1.4491.2.1.20.1.3.2.1.1
                # index: {cm_index}.{us_channel_index}  value: ifIndex of US channel
                OID_CM_US_IFINDEX = "1.3.6.1.4.1.4491.2.1.20.1.3.2.1.1"
                # docsIf3CmtsCmRegStatusMacAddr   1.3.6.1.4.1.4491.2.1.20.1.3.1.1.3
                # index: {cm_index}  value: MAC as 6 hex octets
                OID_CM_REG_MAC    = "1.3.6.1.4.1.4491.2.1.20.1.3.1.1.3"

                walk = await service._snmp_walk(OID_CM_US_IFINDEX)
                if not isinstance(walk, dict) or not walk.get('success'):
                    return {"success": False, "error": walk.get('error', 'SNMP walk failed'), "modems": []}

                # agent returns {'results': [{oid, value, type}, ...]} (list)
                raw = walk.get('results') or []
                if isinstance(raw, list):
                    oid_map = {item['oid']: item['value'] for item in raw if isinstance(item, dict) and 'oid' in item}
                elif isinstance(raw, dict):
                    oid_map = raw
                else:
                    oid_map = {}

                matching_cm_idx: set = set()
                for oid, val in oid_map.items():
                    try:
                        ifidx = int(str(val).split()[-1])
                        if ifidx == ofdma_ifindex:
                            # index ends with {cm_index}.{channel_index}
                            parts = str(oid).rstrip('.').split('.')
                            cm_idx = int(parts[-2])
                            matching_cm_idx.add(cm_idx)
                    except (ValueError, IndexError):
                        continue

                modems = []
                for cm_idx in list(matching_cm_idx)[:max_modems]:
                    mac_result = await service._snmp_get(f"{OID_CM_REG_MAC}.{cm_idx}")
                    if not mac_result.get('success'):
                        continue
                    raw = service._parse_get_value(mac_result) or ""
                    # raw is hex bytes like 'D4 6A 6A FD 00 B3'
                    parts = raw.replace("0x", "").strip().split()
                    if len(parts) == 6:
                        mac = ":".join(p.lower().zfill(2) for p in parts)
                        modems.append({"cm_mac_address": mac, "cm_index": cm_idx})

                return {"success": True, "ofdma_ifindex": ofdma_ifindex, "modems": modems}
            except Exception as e:
                self.logger.error(f"channel/modems error: {e}")
                return {"success": False, "error": str(e), "modems": []}
            finally:
                service.close()


# Required for dynamic auto-registration
router = UsOfdmaRxMerRouter().router
