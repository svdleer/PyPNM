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
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import Response

from pypnm.lib.pnm_file_source import (
    fetch_pnm_files as _fetch_pnm_files,
    delete_pnm_files as _delete_pnm_files,
    local_pnm_dir as _local_pnm_dir,
    get_cache_dir as _get_cache_dir,
    is_ftp_mode as _is_ftp_mode,
)

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
    PreEqDataRequest,
    PreEqDataResponse,
    PlantAssessmentRequest,
    PlantAssessmentResponse,
    ModemPlantVerdict,
    FnPlantStats,
)
from pypnm.api.routes.pnm.us.ofdma.rxmer.service import CmtsUsOfdmaRxMerService
from pypnm.api.routes.common.service.fiber_node_utils import (
    OID_MD_CH_CFG_CH_ID,
    OID_MD_NODE_STATUS_MD_US_SG_ID,
    OID_MD_US_SG_STATUS_CH_SET_ID,
    OID_US_CH_SET_CH_LIST,
    parse_fn_name_from_oid,
    parse_channel_id_list,
)


class UsOfdmaRxMerRouter:
    """Router for CMTS Upstream OFDMA RxMER operations."""

    # In-memory cache for channel/list results: {cmts_ip: (timestamp, response_dict)}
    _channel_list_cache: dict[str, tuple[float, dict]] = {}
    _CHANNEL_LIST_TTL = 259200  # 72 hours — fiber nodes are static
    
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
            "/preeq",
            summary="Get pre-equalization data and group delay",
            response_model=PreEqDataResponse,
        )
        async def get_preeq_data(
            request: PreEqDataRequest
        ) -> PreEqDataResponse:
            """
            Get ATDMA pre-equalization coefficients and group delay for a cable modem.
            
            This endpoint queries docsIf3CmtsCmUsStatusEqData and computes:
            - Pre-equalization tap coefficients
            - Key metrics (MTC, NMTER, tap energy ratios)
            - Group delay variation (derived from phase response)
            - Cable length equivalents for micro-reflections
            
            Group delay analysis helps identify:
            - Network issues: Large group delay variation across all modems on a fiber node
            - In-home issues: High group delay for a single modem (micro-reflections, impedance mismatches)
            """
            self.logger.info(
                f"Getting pre-EQ for CM {request.cm_mac_address} on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                # Get cm_index if not provided
                cm_index = request.cm_index
                if not cm_index:
                    cm_index = await service.discover_cm_index(request.cm_mac_address)
                    if not cm_index:
                        return PreEqDataResponse(
                            success=False,
                            cm_mac_address=request.cm_mac_address,
                            error="CM not found on CMTS"
                        )
                
                result = await service.get_preeq_data(
                    cm_index=cm_index,
                    channel_width_hz=request.channel_width_hz
                )
                return PreEqDataResponse(
                    success=result.get('success', False),
                    cm_mac_address=request.cm_mac_address,
                    cm_index=result.get('cm_index'),
                    num_channels=result.get('num_channels', 0),
                    channels=result.get('channels', []),
                    error=result.get('error')
                )
            finally:
                service.close()

        @self.router.post(
            "/fiberNode/plant-assessment",
            summary="Fiber node plant vs in-home assessment (pre-eq + RxMER combined)",
            response_model=PlantAssessmentResponse,
        )
        async def fiber_node_plant_assessment(
            request: PlantAssessmentRequest,
        ) -> PlantAssessmentResponse:
            """
            Classify each modem on a fiber node as 'plant', 'in-home', 'clean', or 'unknown'
            by combining three signals:

            1. **Tap shape similarity** — normalized pre-eq magnitude cosine similarity vs FN median.
               Low similarity (unique tap shape) = in-home indicator.

            2. **Group delay deviation** — |modem gd_pp - FN median gd_pp| > threshold = in-home.

            3. **Shared impaired subcarriers** — subcarriers bad on >plant_share_pct of modems
               = plant-side ingress or interference.

            Decision table:
            - Unique tap AND gd outlier                             → in-home (high confidence)
            - Unique tap OR gd outlier + no shared subcarriers      → in-home (medium confidence)
            - Shared bad subcarriers >60% + similar tap to FN       → plant
            - NMTER < 25 dB AND similar tap to FN median            → plant
            - All metrics nominal                                    → clean
            """
            import math as _math
            import statistics as _stat

            try:
                mod_preeq = request.modems_preeq
                sc_stats = request.subcarrier_stats
                thr = request.mer_bad_threshold_db
                sim_thr = request.tap_similarity_threshold
                gd_thr = request.gd_deviation_threshold_us
                plant_share = request.plant_share_pct

                n_modems = len(mod_preeq)
                if n_modems == 0:
                    return PlantAssessmentResponse(success=False, error="No modem pre-eq data provided")

                # ── Build per-modem tap magnitude vectors (use first channel available)
                # also returns (offsets, dB_rel_to_main, cable_ft, main_tap_loc, sample_period_us)
                _COAX_VELOCITY_M_S = 0.85 * 299_792_458   # ~2.548e8 m/s (VOP 0.85)
                _M_TO_FT = 3.28084

                def _tap_profile(channels):
                    """Return (norm_vec, offsets, dB_rel, cable_ft, main_loc, sp_us) for first usable channel."""
                    for ch in channels:
                        taps = ch.taps
                        if not taps:
                            continue
                        mags = [t.magnitude for t in taps]
                        mx = max(mags) if mags else 0.0
                        norm_vec = [m / mx if mx > 0 else 0.0 for m in mags]

                        # main tap = argmax (or use header main_tap_location if provided)
                        main_loc = ch.main_tap_location if ch.main_tap_location is not None else int(mags.index(mx))
                        main_mag = mags[main_loc] if main_loc < len(mags) else mx

                        offsets = [i - main_loc for i in range(len(mags))]

                        dB_rel: list = []
                        for m in mags:
                            if m > 0 and main_mag > 0:
                                dB_rel.append(round(20 * _math.log10(m / main_mag), 2))
                            else:
                                dB_rel.append(None)

                        sp_us: float | None = None
                        if ch.group_delay and ch.group_delay.sample_period_us:
                            sp_us = ch.group_delay.sample_period_us

                        cable_ft: list = []
                        for off in offsets:
                            if off == 0 or sp_us is None:
                                cable_ft.append(None)
                            else:
                                delay_s = abs(off) * sp_us * 1e-6
                                dist_m  = delay_s * _COAX_VELOCITY_M_S / 2.0  # one-way (reflection round-trip /2)
                                cable_ft.append(round(dist_m * _M_TO_FT, 1))

                        return norm_vec, offsets, dB_rel, cable_ft, main_loc, sp_us
                    return [], [], [], [], None, None

                mac_to_tap_vec:     dict = {}
                mac_to_tap_profile: dict = {}  # mac -> (offsets, dB_rel, cable_ft, main_loc, sp_us)
                for mp in mod_preeq:
                    norm_vec, offsets, dB_rel, cable_ft, main_loc, sp_us = _tap_profile(mp.channels)
                    if norm_vec:
                        mac_to_tap_vec[mp.mac] = norm_vec
                        mac_to_tap_profile[mp.mac] = (offsets, dB_rel, cable_ft, main_loc, sp_us)

                # ── FN-median tap signature (element-wise median, align by length)
                all_vecs = list(mac_to_tap_vec.values())
                fn_tap_sig: list[float] = []
                fn_tap_offsets: list[int] = []
                fn_tap_dB: list = []
                fn_tap_cable_ft: list = []
                fn_main_tap_loc: int | None = None
                fn_sample_period_us: float | None = None
                if all_vecs:
                    min_len = min(len(v) for v in all_vecs)
                    fn_tap_sig = [
                        _stat.median(v[i] for v in all_vecs)
                        for i in range(min_len)
                    ]
                    # Modal main tap location and median sample period across modems
                    all_main_locs = [p[3] for p in mac_to_tap_profile.values() if p[3] is not None]
                    fn_main_tap_loc = int(_stat.mode(all_main_locs)) if all_main_locs else None
                    all_sp = [p[4] for p in mac_to_tap_profile.values() if p[4] is not None]
                    fn_sample_period_us = _stat.median(all_sp) if all_sp else None
                    if fn_main_tap_loc is not None:
                        fn_tap_offsets = [i - fn_main_tap_loc for i in range(min_len)]
                        fn_tap_dB = [
                            (round(20 * _math.log10(v) if v > 0 else None, 2)
                             if v > 0 else None)
                            for v in fn_tap_sig
                        ]
                        fn_tap_cable_ft = []
                        for off in fn_tap_offsets:
                            if off == 0 or fn_sample_period_us is None:
                                fn_tap_cable_ft.append(None)
                            else:
                                delay_s = abs(off) * fn_sample_period_us * 1e-6
                                dist_m  = delay_s * _COAX_VELOCITY_M_S / 2.0
                                fn_tap_cable_ft.append(round(dist_m * _M_TO_FT, 1))

                def _cosine_sim(a: list[float], b: list[float]) -> float:
                    n = min(len(a), len(b))
                    if n == 0:
                        return 0.0
                    dot = sum(a[i] * b[i] for i in range(n))
                    na = _math.sqrt(sum(x * x for x in a[:n]))
                    nb = _math.sqrt(sum(x * x for x in b[:n]))
                    return dot / (na * nb) if na > 0 and nb > 0 else 0.0

                # ── Group delay per modem (use first channel)
                def _gd_pp(channels) -> float | None:
                    for ch in channels:
                        if ch.group_delay and ch.group_delay.delay_pp_us is not None:
                            return ch.group_delay.delay_pp_us
                    return None

                def _nmter(channels) -> float | None:
                    for ch in channels:
                        if ch.metrics and ch.metrics.nmter_dB is not None:
                            return ch.metrics.nmter_dB
                    return None

                mac_to_gd: dict = {}
                mac_to_nmter: dict = {}
                for mp in mod_preeq:
                    gd = _gd_pp(mp.channels)
                    if gd is not None:
                        mac_to_gd[mp.mac] = gd
                    nt = _nmter(mp.channels)
                    if nt is not None:
                        mac_to_nmter[mp.mac] = nt

                gd_values = list(mac_to_gd.values())
                fn_median_gd = _stat.median(gd_values) if gd_values else None
                nmter_values = list(mac_to_nmter.values())
                fn_median_nmter = _stat.median(nmter_values) if nmter_values else None

                # ── Per-subcarrier bad-modem count from subcarrier_stats
                # subcarrier_stats[i].values_db is a list of MER per capture
                # outlier_macs lists MACs that are 2σ below group mean
                # Use outlier_macs as proxy for bad-subcarrier membership
                mac_bad_sc: dict = {}      # mac -> set of sc indices
                sc_shared_bad: set = set() # sc indices bad on >= plant_share fraction
                sc_shared_freqs: dict = {} # sc index -> freq_mhz

                if sc_stats:
                    sc_modem_bad_count: dict[int, int] = {}  # sc_idx -> count of bad modems
                    sc_bad_macs: dict[int, set] = {}
                    for sc in sc_stats:
                        bad_macs = set(sc.outlier_macs)
                        sc_bad_macs[sc.index] = bad_macs
                        sc_modem_bad_count[sc.index] = len(bad_macs)
                        for mac in bad_macs:
                            mac_bad_sc.setdefault(mac, set()).add(sc.index)

                    for sc_idx, cnt in sc_modem_bad_count.items():
                        if n_modems > 0 and cnt / n_modems >= plant_share:
                            sc_shared_bad.add(sc_idx)

                    for sc in sc_stats:
                        if sc.index in sc_shared_bad:
                            sc_shared_freqs[sc.index] = sc.frequency_mhz

                # ── Per-modem verdict
                verdicts: list[ModemPlantVerdict] = []
                for mp in mod_preeq:
                    mac = mp.mac
                    gd_pp = mac_to_gd.get(mac)
                    nmter = mac_to_nmter.get(mac)
                    tap_vec    = mac_to_tap_vec.get(mac, [])
                    tap_prof   = mac_to_tap_profile.get(mac, ([], [], [], None, None))
                    tap_offsets, tap_dB_rel, tap_cable_ft, tap_main_loc, tap_sp_us = tap_prof
                    tap_sim = _cosine_sim(tap_vec, fn_tap_sig) if (tap_vec and fn_tap_sig) else None
                    gd_dev = abs(gd_pp - fn_median_gd) if (gd_pp is not None and fn_median_gd is not None) else None

                    bad_sc = mac_bad_sc.get(mac, set())
                    unique_bad = len(bad_sc - sc_shared_bad)
                    shared_bad = len(bad_sc & sc_shared_bad)

                    evidence: list[str] = []
                    inhome_score = 0.0
                    plant_score = 0.0

                    if tap_sim is not None:
                        if tap_sim < sim_thr:
                            inhome_score += 0.45
                            evidence.append(f"Unique tap shape (similarity {tap_sim:.2f} < {sim_thr})")
                        else:
                            plant_score += 0.2
                            evidence.append(f"Tap shape matches FN median (similarity {tap_sim:.2f})")

                    if gd_dev is not None:
                        if gd_dev > gd_thr:
                            inhome_score += 0.35
                            evidence.append(f"GD deviation {gd_dev:.3f}µs > {gd_thr}µs threshold")
                        else:
                            plant_score += 0.15

                    if unique_bad > 0:
                        inhome_score += min(0.20, unique_bad / max(len(bad_sc), 1) * 0.20)
                        evidence.append(f"{unique_bad} unique bad subcarriers (not shared with FN)")

                    if shared_bad > 0:
                        plant_score += min(0.40, shared_bad / max(len(bad_sc), 1) * 0.40)
                        evidence.append(f"{shared_bad} shared impaired subcarriers (plant ingress)")

                    if nmter is not None and nmter < 25.0:
                        plant_score += 0.25
                        evidence.append(f"Low NMTER {nmter:.1f} dB shared with FN (NMTER < 25 dB)")

                    if inhome_score >= 0.5 and inhome_score > plant_score:
                        verdict = "in-home"
                        confidence = round(min(inhome_score, 1.0), 2)
                    elif plant_score >= 0.35 and plant_score >= inhome_score:
                        verdict = "plant"
                        confidence = round(min(plant_score, 1.0), 2)
                    elif inhome_score < 0.2 and plant_score < 0.2:
                        verdict = "clean"
                        confidence = 0.9
                        evidence.append("All metrics nominal")
                    else:
                        verdict = "unknown"
                        confidence = 0.0

                    verdicts.append(ModemPlantVerdict(
                        mac=mac,
                        verdict=verdict,
                        confidence=confidence,
                        tap_similarity_to_fn_median=round(tap_sim, 4) if tap_sim is not None else None,
                        gd_pp_us=gd_pp,
                        gd_deviation_from_fn_median_us=round(gd_dev, 4) if gd_dev is not None else None,
                        nmter_dB=nmter,
                        unique_bad_subcarrier_count=unique_bad,
                        shared_bad_subcarrier_count=shared_bad,
                        evidence=evidence,
                        main_tap_location=tap_main_loc,
                        tap_offsets=tap_offsets,
                        tap_dB_relative_to_main=tap_dB_rel,
                        tap_cable_ft=tap_cable_ft,
                        sample_period_us=tap_sp_us,
                    ))

                n_inhome = sum(1 for v in verdicts if v.verdict == "in-home")
                n_plant = sum(1 for v in verdicts if v.verdict == "plant")

                fn_stats = FnPlantStats(
                    modem_count=n_modems,
                    fn_median_gd_pp_us=round(fn_median_gd, 4) if fn_median_gd is not None else None,
                    fn_median_nmter_dB=round(fn_median_nmter, 2) if fn_median_nmter is not None else None,
                    fn_tap_signature=[round(v, 4) for v in fn_tap_sig],
                    fn_tap_offsets=fn_tap_offsets,
                    fn_tap_dB_relative_to_main=fn_tap_dB,
                    fn_tap_cable_ft=fn_tap_cable_ft,
                    fn_main_tap_location=fn_main_tap_loc,
                    fn_sample_period_us=fn_sample_period_us,
                    shared_impaired_subcarrier_indices=sorted(sc_shared_bad),
                    shared_impaired_frequencies_mhz=[
                        sc_shared_freqs[i] for i in sorted(sc_shared_bad) if i in sc_shared_freqs
                    ],
                    plant_issue_detected=len(sc_shared_bad) > 0 or n_plant > 0,
                    pct_modems_in_home=round(n_inhome / n_modems * 100, 1) if n_modems else 0.0,
                    pct_modems_plant=round(n_plant / n_modems * 100, 1) if n_modems else 0.0,
                )

                return PlantAssessmentResponse(
                    success=True,
                    fn_stats=fn_stats,
                    modem_verdicts=verdicts,
                )

            except Exception as exc:
                self.logger.exception(f"plant-assessment error: {exc}")
                return PlantAssessmentResponse(success=False, error=str(exc))

        @self.router.post(
            "/fiberNode/tap-plot",
            summary="Pre-equalizer tap distance plot (matplotlib PNG)",
            response_class=Response,
        )
        async def fiber_node_tap_plot(
            request: PlantAssessmentRequest,
        ) -> Response:
            """
            Render a matplotlib figure showing the pre-equalizer tap magnitude
            profile (dB relative to main tap) for every modem on the fiber node.

            - X-axis : tap offset from main tap (tap numbers); top twin axis in
              estimated one-way cable distance (ft) when sample_period_us is available.
            - Y-axis : magnitude relative to main tap (dB).  Main tap = 0 dB.
            - One line per modem coloured by plant-assessment verdict:
                green = clean, yellow = in-home, red = plant, grey = unknown.
            - Thick dashed black line = FN median profile.
            - Vertical red line at x=0 marks the main tap.
            """
            import io as _io
            import math as _math
            import statistics as _stat
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.ticker as mticker
            import numpy as np

            _COAX_VEL = 0.85 * 299_792_458   # m/s  (VOP 0.85)
            _M_TO_FT  = 3.28084

            VERDICT_COLOUR = {
                "clean":   "#2ca02c",  # green
                "in-home": "#ff7f0e",  # orange
                "plant":   "#d62728",  # red
                "unknown": "#9467bd",  # purple
            }

            try:
                mod_preeq = request.modems_preeq
                n_modems  = len(mod_preeq)
                if n_modems == 0:
                    return Response(
                        content=b"",
                        status_code=400,
                        media_type="image/png",
                    )

                # ── helpers (same logic as plant-assessment endpoint)
                def _tap_profile(channels):
                    for ch in channels:
                        taps = ch.taps
                        if not taps:
                            continue
                        mags    = [t.magnitude for t in taps]
                        mx      = max(mags) if mags else 0.0
                        norm    = [m / mx if mx > 0 else 0.0 for m in mags]
                        main_l  = ch.main_tap_location if ch.main_tap_location is not None \
                                  else int(mags.index(mx))
                        main_m  = mags[main_l] if main_l < len(mags) else mx
                        offsets = [i - main_l for i in range(len(mags))]
                        dB_rel  = [
                            round(20 * _math.log10(m / main_m), 2)
                            if (m > 0 and main_m > 0) else None
                            for m in mags
                        ]
                        sp_us   = (ch.group_delay.sample_period_us
                                   if ch.group_delay and ch.group_delay.sample_period_us
                                   else None)
                        return norm, offsets, dB_rel, main_l, sp_us
                    return [], [], [], None, None

                mac_norm:    dict = {}
                mac_profile: dict = {}
                for mp in mod_preeq:
                    norm, offsets, dB_rel, main_l, sp_us = _tap_profile(mp.channels)
                    if norm:
                        mac_norm[mp.mac]    = norm
                        mac_profile[mp.mac] = (offsets, dB_rel, main_l, sp_us)

                # FN median profile
                all_vecs   = list(mac_norm.values())
                fn_dB:      list = []
                fn_offsets: list = []
                fn_sp_us:   float | None = None
                fn_main_l:  int | None   = None
                if all_vecs:
                    min_len = min(len(v) for v in all_vecs)
                    fn_sig  = [_stat.median(v[i] for v in all_vecs) for i in range(min_len)]
                    all_ml  = [p[2] for p in mac_profile.values() if p[2] is not None]
                    fn_main_l = int(_stat.mode(all_ml)) if all_ml else None
                    all_sp  = [p[3] for p in mac_profile.values() if p[3] is not None]
                    fn_sp_us = _stat.median(all_sp) if all_sp else None
                    if fn_main_l is not None:
                        mxv = fn_sig[fn_main_l] if fn_main_l < len(fn_sig) else max(fn_sig, default=1e-9)
                        fn_offsets = [i - fn_main_l for i in range(min_len)]
                        fn_dB = [
                            round(20 * _math.log10(v / mxv), 2)
                            if (v > 0 and mxv > 0) else None
                            for v in fn_sig
                        ]

                # Quick verdict colours (cosine similarity only — no need for full scoring)
                def _cosine_sim(a, b):
                    n = min(len(a), len(b))
                    if n == 0: return 0.0
                    dot = sum(a[i]*b[i] for i in range(n))
                    na  = _math.sqrt(sum(x*x for x in a[:n]))
                    nb  = _math.sqrt(sum(x*x for x in b[:n]))
                    return dot / (na*nb) if na > 0 and nb > 0 else 0.0

                fn_sig_for_sim = list(mac_norm.values())[0] if mac_norm else []
                if all_vecs:
                    min_l = min(len(v) for v in all_vecs)
                    fn_sig_for_sim = [_stat.median(v[i] for v in all_vecs) for i in range(min_l)]

                mac_verdict: dict = {}
                sim_thr = request.tap_similarity_threshold
                gd_thr  = request.gd_deviation_threshold_us
                all_gd  = []
                for mp in mod_preeq:
                    for ch in mp.channels:
                        if ch.group_delay and ch.group_delay.delay_pp_us is not None:
                            all_gd.append(ch.group_delay.delay_pp_us)
                            break
                fn_gd = _stat.median(all_gd) if all_gd else None
                mac_gd: dict = {}
                for mp in mod_preeq:
                    for ch in mp.channels:
                        if ch.group_delay and ch.group_delay.delay_pp_us is not None:
                            mac_gd[mp.mac] = ch.group_delay.delay_pp_us
                            break

                for mp in mod_preeq:
                    vec = mac_norm.get(mp.mac, [])
                    sim = _cosine_sim(vec, fn_sig_for_sim) if (vec and fn_sig_for_sim) else None
                    gd  = mac_gd.get(mp.mac)
                    gd_dev = abs(gd - fn_gd) if (gd is not None and fn_gd is not None) else None
                    if sim is not None and sim < sim_thr:
                        mac_verdict[mp.mac] = "in-home"
                    elif gd_dev is not None and gd_dev > gd_thr:
                        mac_verdict[mp.mac] = "in-home"
                    else:
                        mac_verdict[mp.mac] = "clean"   # coarse — plant needs sc_stats

                # ── Assign a unique colour per modem from tab20 / tab20b cycle ────
                _CMAP_NAMES = ["tab20", "tab20b", "tab20c"]
                _all_colours: list = []
                for _cn in _CMAP_NAMES:
                    _cm = plt.get_cmap(_cn)
                    _all_colours.extend([_cm(i) for i in range(_cm.N)])
                # linestyle encodes verdict so colour encodes identity
                VERDICT_LS = {
                    "clean":   ("solid",  1.3),
                    "in-home": ("dashed", 1.6),
                    "plant":   ((0, (3, 1, 1, 1)), 2.0),  # dash-dot
                    "unknown": ("dotted", 1.0),
                }

                # ── Figure: main plot + legend table below ────────────────────────
                # Reserve extra height for the legend table
                n_cols_leg    = 3
                legend_rows   = max(1, -(-n_modems // n_cols_leg))   # ceil div
                leg_height_in = legend_rows * 0.26 + 0.5
                fig_height    = 5.5 + leg_height_in

                fig = plt.figure(figsize=(14, fig_height))
                fig.patch.set_facecolor("#f8f9fa")

                # GridSpec: top = plot, bottom = legend area
                import matplotlib.gridspec as gridspec
                gs = gridspec.GridSpec(
                    2, 1,
                    height_ratios=[5.5, leg_height_in],
                    hspace=0.35,
                    figure=fig,
                )
                ax     = fig.add_subplot(gs[0])
                ax_leg = fig.add_subplot(gs[1])
                ax_leg.axis("off")
                ax.set_facecolor("#ffffff")

                plotted      = []   # list of (mac, colour, linestyle, verdict)
                colour_cycle = iter(_all_colours)
                for mp in mod_preeq:
                    mac  = mp.mac
                    prof = mac_profile.get(mac)
                    if not prof:
                        continue
                    offsets, dB_rel, _, _ = prof
                    verdict = mac_verdict.get(mac, "unknown")
                    ls, lw  = VERDICT_LS.get(verdict, ("dotted", 1.0))
                    colour  = next(colour_cycle, "#aaaaaa")
                    ys      = [v if v is not None else float("nan") for v in dB_rel]
                    ax.plot(offsets, ys, color=colour, linestyle=ls,
                            alpha=0.80, linewidth=lw)
                    plotted.append((mac, colour, ls, verdict))

                # FN median overlay
                if fn_dB and fn_offsets:
                    fn_ys = [v if v is not None else float("nan") for v in fn_dB]
                    ax.plot(fn_offsets, fn_ys,
                            color="black", linewidth=2.5, linestyle="--",
                            label="FN median", zorder=5)

                # Reference lines
                ax.axvline(0, color="#cc0000", linewidth=1.5, linestyle="-",
                           zorder=3, alpha=0.7, label="Main tap")
                for ref_dB in (-20, -30, -40):
                    ax.axhline(ref_dB, color="#aaaaaa", linewidth=0.7,
                               linestyle=":", zorder=1)
                    ax.text(ax.get_xlim()[0] if ax.get_xlim()[0] != 0 else -1,
                            ref_dB + 0.5, f"{ref_dB} dB",
                            fontsize=7, color="#888888", va="bottom")

                ax.set_xlabel("Tap offset from main tap (samples)", fontsize=10)
                ax.set_ylabel("Magnitude relative to main tap (dB)", fontsize=10)
                ax.set_title(
                    f"Pre-Eq Tap Distance Profile — {n_modems} modems"
                    + (f"  |  sample period {fn_sp_us:.3f} µs" if fn_sp_us else ""),
                    fontsize=11, fontweight="bold",
                )
                ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.0f"))
                ax.grid(True, which="major", linestyle="--", alpha=0.3)
                # Center 0 dB in the middle of the Y-axis: compute symmetric range
                # from the actual data so the main tap (0 dB) is always at mid-height.
                all_dB_vals = [
                    v
                    for mp in mod_preeq
                    for _, dB_rel, _, _ in [mac_profile.get(mp.mac, ([], [], None, None))]
                    for v in dB_rel
                    if v is not None
                ]
                if fn_dB:
                    all_dB_vals += [v for v in fn_dB if v is not None]
                if all_dB_vals:
                    max_abs = max(abs(min(all_dB_vals)), abs(max(all_dB_vals)))
                    pad = max(2.0, max_abs * 0.08)
                    _symmetric = max_abs + pad
                    ax.set_ylim(bottom=-_symmetric, top=_symmetric)
                else:
                    ax.set_ylim(bottom=-55, top=3)

                # Small in-plot legend for verdict line-styles only
                from matplotlib.lines import Line2D
                style_handles = [
                    Line2D([0], [0], color="grey", linestyle=ls, linewidth=lw,
                           label=v.capitalize())
                    for v, (ls, lw) in VERDICT_LS.items()
                ] + [
                    Line2D([0], [0], color="black",  linestyle="--", linewidth=2.5, label="FN median"),
                    Line2D([0], [0], color="#cc0000", linestyle="-",  linewidth=1.5, label="Main tap"),
                ]
                ax.legend(handles=style_handles, loc="lower right",
                          fontsize=8, framealpha=0.85,
                          title="Line style = verdict", title_fontsize=7)

                # Twin top x-axis in cable ft (when sample_period_us known)
                if fn_sp_us and fn_sp_us > 0:
                    ax2 = ax.twiny()
                    ax2.set_xlim(ax.get_xlim())
                    def tap_to_ft(x):
                        delay_s = abs(x) * fn_sp_us * 1e-6
                        return delay_s * _COAX_VEL / 2.0 * _M_TO_FT
                    tick_offs = sorted(set(
                        [o for o in fn_offsets if o != 0] or [1]
                    ), key=abs)
                    step  = max(1, len(tick_offs) // 8)
                    shown = [0] + tick_offs[::step]
                    ax2.set_xticks(shown)
                    ax2.set_xticklabels(
                        ["main" if t == 0 else f"{tap_to_ft(t):.0f} ft"
                         for t in shown],
                        fontsize=8,
                    )
                    ax2.set_xlabel(
                        "Estimated one-way reflection distance (ft, VOP 0.85)",
                        fontsize=9,
                    )

                # ── Legend table below the plot ───────────────────────────────────
                # Columns: colour swatch | MAC address | verdict badge
                VERDICT_BG = {
                    "clean":   "#d4edda", "in-home": "#fff3cd",
                    "plant":   "#f8d7da", "unknown": "#e2e3e5",
                }
                col_w   = 1.0 / n_cols_leg
                row_h   = 1.0 / max(legend_rows + 1, 2)
                # Header row
                for ci, hdr in enumerate(["MAC address", "Verdict"] * n_cols_leg):
                    pass   # skip — use coloured patches as header implicitly

                for idx, (mac, colour, ls, verdict) in enumerate(plotted):
                    row = idx // n_cols_leg
                    col = idx %  n_cols_leg
                    x0  = col * col_w
                    y0  = 1.0 - (row + 1) * row_h

                    # Coloured rectangle (modem colour)
                    swatch_w = col_w * 0.06
                    rect = plt.matplotlib.patches.FancyBboxPatch(
                        (x0 + 0.005, y0 + row_h * 0.15),
                        swatch_w, row_h * 0.65,
                        boxstyle="round,pad=0.01",
                        facecolor=colour, edgecolor="none",
                        clip_on=False,
                    )
                    rect.set_transform(ax_leg.transAxes)
                    ax_leg.add_patch(rect)

                    # MAC address
                    ax_leg.text(
                        x0 + swatch_w + 0.015, y0 + row_h * 0.5,
                        mac,
                        transform=ax_leg.transAxes,
                        fontsize=7.5, fontfamily="monospace",
                        va="center", ha="left",
                        color="#222222",
                    )

                    # Verdict badge (right of MAC)
                    badge_x = x0 + col_w * 0.62
                    bg = VERDICT_BG.get(verdict, "#e2e3e5")
                    badge_rect = plt.matplotlib.patches.FancyBboxPatch(
                        (badge_x, y0 + row_h * 0.2),
                        col_w * 0.34, row_h * 0.6,
                        boxstyle="round,pad=0.01",
                        facecolor=bg, edgecolor="#aaaaaa", linewidth=0.5,
                        clip_on=False,
                    )
                    badge_rect.set_transform(ax_leg.transAxes)
                    ax_leg.add_patch(badge_rect)
                    ax_leg.text(
                        badge_x + col_w * 0.17, y0 + row_h * 0.5,
                        verdict,
                        transform=ax_leg.transAxes,
                        fontsize=7, va="center", ha="center",
                        color="#333333", fontweight="bold",
                    )

                # Thin separator line between plot and legend
                ax_leg.plot([0, 1], [1.0, 1.0], color="#cccccc", linewidth=0.8,
                            transform=ax_leg.transAxes, clip_on=False)

                buf = _io.BytesIO()
                fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
                plt.close(fig)
                buf.seek(0)
                return Response(content=buf.getvalue(), media_type="image/png")

            except Exception as exc:
                self.logger.exception(f"tap-plot error: {exc}")
                buf = _io.BytesIO()
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                fig, ax = plt.subplots(figsize=(6, 2))
                ax.text(0.5, 0.5, f"Plot error: {exc}",
                        ha="center", va="center", transform=ax.transAxes, color="red")
                fig.savefig(buf, format="png", dpi=72)
                plt.close(fig)
                buf.seek(0)
                return Response(content=buf.getvalue(), media_type="image/png")

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
                    tftp_server=request.tftp_server,
                    dest_path=request.dest_path
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
            
            # Build file path - CMTS adds timestamp, so use glob to find latest.
            # In hybrid deployments (PNM_FILE_SOURCE=agent/local + FTP configured),
            # still include cache dir lookup for API-side FTP retrieval.
            tftp_dir = _local_pnm_dir() if _is_ftp_mode() else Path(request.tftp_path)
            cache_dir = Path(_get_cache_dir())

            # Strip leading '/' — Cisco/E6000 SNMP returns e.g. /pnm/mer/usrxmer_xxx
            # which Python's Path join treats as absolute, discarding tftp_dir entirely.
            filename = request.filename.lstrip('/')

            # Try API-side FTP prefetch for this capture prefix in both ftp and hybrid modes.
            basename = Path(filename).name
            try:
                _fetch_pnm_files(basename, allow_when_local=True)
            except Exception as e:
                self.logger.warning(f"FTP prefetch skipped for {basename}: {e}")

            # First try exact filename
            filepath = tftp_dir / filename
            if not filepath.exists():
                filepath = cache_dir / filename

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
                    str(cache_dir / f"{filename}_*"),
                    str(cache_dir / "**" / basename),
                    str(cache_dir / "**" / f"{basename}_*"),
                ]:
                    matching_files = sorted(glob.glob(pattern, recursive=True), reverse=True)
                    if matching_files:
                        filepath = Path(matching_files[0])
                        self.logger.info(f"Found file via pattern '{pattern}': {filepath}")
                        break
                else:
                    self.logger.error(f"File not found: tried {tftp_dir / filename} and {cache_dir / filename}")
                    return UsOfdmaRxMerCaptureResponse(
                        success=False,
                        error=f"File not found: {basename}"
                    )
            
            self.logger.info(f"Loading US RxMER file: {filepath}")
            
            try:
                # Read and parse file
                data = filepath.read_bytes()
                # Housekeeping: file in memory — delete from FTP + local cache
                if _is_ftp_mode():
                    _delete_pnm_files(basename)
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

            tftp_dir = _local_pnm_dir() if _is_ftp_mode() else Path(request.tftp_path)
            cache_dir = Path(_get_cache_dir())
            filename = request.filename.lstrip('/')
            basename = Path(filename).name
            try:
                _fetch_pnm_files(basename, allow_when_local=True)
            except Exception as e:
                self.logger.warning(f"FTP prefetch skipped for {basename}: {e}")
            filepath = tftp_dir / filename
            if not filepath.exists():
                filepath = cache_dir / filename

            if not filepath.exists():
                basename = Path(filename).name
                for pattern in [
                    str(tftp_dir / f"{filename}_*"),
                    str(tftp_dir / "**" / basename),
                    str(tftp_dir / "**" / f"{basename}_*"),
                    str(cache_dir / f"{filename}_*"),
                    str(cache_dir / "**" / basename),
                    str(cache_dir / "**" / f"{basename}_*"),
                ]:
                    matching_files = sorted(glob.glob(pattern, recursive=True), reverse=True)
                    if matching_files:
                        filepath = Path(matching_files[0])
                        break
                else:
                    return UsOfdmaRxMerCaptureResponse(
                        success=False,
                        error=f"File not found: {Path(filename).name}"
                    )

            try:
                data = filepath.read_bytes()
                # Housekeeping: file in memory — delete from FTP + local cache
                if _is_ftp_mode():
                    _delete_pnm_files(basename)
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

        def _load_rxmer_capture(filename: str, tftp_path: str, preeq_enabled: bool,
                                cm_mac: str = None, ofdma_ifindex: int = None) -> RxMerCapture:
            """Parse one RxMER file into a RxMerCapture model."""
            from pypnm.pnm.parser.CmtsUsOfdmaRxMer import CmtsUsOfdmaRxMer
            import glob, statistics as _stat

            def _find_capture(base_dir: Path, key: str):
                if not base_dir:
                    return None
                fn_local = key.lstrip('/')
                fp_local = base_dir / fn_local
                if fp_local.exists():
                    return fp_local
                basename_local = Path(fn_local).name
                for pat in [
                    str(base_dir / f"{fn_local}_*"),
                    str(base_dir / "**" / basename_local),
                    str(base_dir / "**" / f"{basename_local}_*"),
                ]:
                    matches = sorted(glob.glob(pat, recursive=True), reverse=True)
                    if matches:
                        return Path(matches[0])
                return None

            tftp_dir = Path(tftp_path)
            fn = filename.lstrip('/')
            fp = _find_capture(tftp_dir, fn)

            # If missing, always let PyPNM API fetch capture(s) directly from FTP.
            # CMTS RxMER capture retrieval belongs in API, also for hybrid setups
            # where other flows remain local/agent-based.
            if fp is None:
                try:
                    _fetch_pnm_files(Path(fn).name, allow_when_local=True)
                except Exception as e:
                    self.logger.warning(f"FTP fetch skipped for {Path(fn).name}: {e}")
                cache_dir = Path(_get_cache_dir())
                fp = _find_capture(cache_dir, fn)

            if fp is None:
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
                ofdma_ifindex=ofdma_ifindex,
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
            from collections import defaultdict

            if not captures:
                return FiberNodeAnalysis(success=False, error="No captures provided")

            # ----------------------------------------------------------------
            # Group captures by frequency band (50 MHz buckets of first subcarrier).
            # This ensures subcarrier stats are only computed across captures that
            # are on the SAME OFDMA block — captures from different blocks (e.g. a
            # 5-42 MHz low-split block and a 65-204 MHz high-split block) are never
            # aligned by subcarrier index against each other.
            # ----------------------------------------------------------------
            def _band_key(cap):
                f0 = cap.frequencies_mhz[0] if cap.frequencies_mhz else 0.0
                return round(f0 / 50) * 50  # nearest 50 MHz bucket

            bands: dict[int, list] = {}
            for cap in captures:
                bands.setdefault(_band_key(cap), []).append(cap)

            subcarrier_stats: list[SubcarrierGroupStats] = []
            mac_outlier_count: dict[str, int] = defaultdict(int)
            shared_bad_idx_set: set[int] = set()  # global index into subcarrier_stats
            total_sc = 0  # total subcarrier slots across all bands

            for band_f0 in sorted(bands):
                band_caps = bands[band_f0]
                n_band   = min(len(c.values) for c in band_caps)
                n_all    = len(band_caps)
                freqs_b  = band_caps[0].frequencies_mhz[:n_band]

                for i in range(n_band):
                    sc_vals = [c.values[i] for c in band_caps if c.values[i] < 63.5]
                    if not sc_vals:
                        sc_vals = [0.0]
                    mean = round(_stat.mean(sc_vals), 2)
                    std  = round(_stat.stdev(sc_vals), 2) if len(sc_vals) > 1 else 0.0
                    sorted_v = sorted(sc_vals)
                    p10 = round(sorted_v[max(0, int(len(sorted_v) * 0.10))], 2)
                    p90 = round(sorted_v[min(len(sorted_v) - 1, int(len(sorted_v) * 0.90))], 2)
                    outlier_macs = [
                        c.cm_mac_address for c in band_caps
                        if c.values[i] < 63.5 and c.values[i] < mean - 2 * std
                    ]
                    for mac in outlier_macs:
                        mac_outlier_count[mac] += 1
                    global_idx = total_sc + i
                    if len(outlier_macs) > n_all * 0.5:
                        shared_bad_idx_set.add(global_idx)
                    subcarrier_stats.append(SubcarrierGroupStats(
                        frequency_mhz=freqs_b[i] if i < len(freqs_b) else i,
                        index=global_idx,
                        values_db=[round(c.values[i], 2) for c in band_caps],
                        mean_db=mean, std_db=std,
                        min_db=round(min(sc_vals), 2), max_db=round(max(sc_vals), 2),
                        p10_db=p10, p90_db=p90,
                        outlier_macs=outlier_macs,
                    ))
                total_sc += n_band

            n = total_sc  # used for percentage calculations below

            # Group captures by MAC for pre-eq pairing
            by_mac: dict[str, list] = {}
            for c in captures:
                by_mac.setdefault(c.cm_mac_address, []).append(c)

            # Global group average across all captures
            all_avgs = [c.rxmer_avg_db for c in captures if c.rxmer_avg_db is not None]
            group_avg = round(_stat.mean(all_avgs), 2) if all_avgs else 0.0
            group_std = round(_stat.stdev(all_avgs), 2) if len(all_avgs) > 1 else 0.0

            # Subcarriers bad on >50% of captures (shared network impairment)
            num_caps = len(captures)
            shared_bad_idxs = shared_bad_idx_set
            network_freqs = [subcarrier_stats[i].frequency_mhz
                             for i in sorted(shared_bad_idxs) if i < len(subcarrier_stats)]

            modem_assessments: list[ModemAssessment] = []
            for mac, mac_captures in by_mac.items():
                # Group captures by ifindex so multi-channel modems get
                # per-channel pre-EQ comparison before the results are merged.
                by_ifidx: dict = {}
                for c in mac_captures:
                    by_ifidx.setdefault(c.ofdma_ifindex, []).append(c)

                # Per-channel: collect rxmer_avg and pre-EQ delta
                ch_rxmer: list[float] = []
                all_delta_vals: list[float] = []
                all_improved: int = 0

                for ifidx_caps in by_ifidx.values():
                    ch_on  = [c for c in ifidx_caps if c.preeq_enabled]
                    ch_off = [c for c in ifidx_caps if not c.preeq_enabled]
                    ch_rep = ch_on[0] if ch_on else ifidx_caps[0]
                    if ch_rep.rxmer_avg_db is not None:
                        ch_rxmer.append(ch_rep.rxmer_avg_db)
                    # Pre-EQ comparison — only valid within the same channel
                    if ch_on and ch_off:
                        n_ch = min(len(ch_on[0].values), len(ch_off[0].values))
                        dvs = [ch_on[0].values[i] - ch_off[0].values[i]
                               for i in range(n_ch)
                               if ch_on[0].values[i] < 63.5 and ch_off[0].values[i] < 63.5]
                        all_delta_vals.extend(dvs)
                        all_improved += sum(1 for d in dvs if d > 0.5)

                # Merged representative capture (prefer preeq_on, else first)
                on_list  = [c for c in mac_captures if c.preeq_enabled]
                off_list = [c for c in mac_captures if not c.preeq_enabled]
                rep = on_list[0] if on_list else mac_captures[0]

                # rxmer_avg = mean across all channels this modem was scanned on
                mac_avg = round(_stat.mean(ch_rxmer), 2) if ch_rxmer else (rep.rxmer_avg_db or 0.0)
                delta_from_group = round(mac_avg - group_avg, 2)

                # Outlier score based on band-grouped subcarrier stats
                m_outlier_cnt = mac_outlier_count.get(mac, 0)
                outlier_score = round(m_outlier_cnt / n, 3) if n > 0 else 0.0

                # Unique vs shared bad subcarriers (using global indices)
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

                # Pre-EQ comparison — merged deltas across all channels
                preeq_delta_avg = preeq_num_improved = preeq_assessment = None
                if all_delta_vals:
                    preeq_delta_avg  = round(_stat.mean(all_delta_vals), 2)
                    preeq_num_improved = all_improved
                    pct_improved = all_improved / len(all_delta_vals)
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

            # Collect all frequencies across all captures to set xlim
            all_plot_freqs = []
            for i, cap in enumerate(captures):
                n = min(len(cap.values), len(cap.frequencies_mhz))
                label = f"{cap.cm_mac_address} Pre-EQ={'ON' if cap.preeq_enabled else 'OFF'}"
                ax1.plot(cap.frequencies_mhz[:n], cap.values[:n],
                         color=colors[i], linewidth=1.2, alpha=0.85, label=label)
                all_plot_freqs.extend(cap.frequencies_mhz[:n])

            ax1.axhline(y=35, color='#4CAF50', linestyle='--', alpha=0.6, linewidth=1, label='Good (≥35 dB)')
            ax1.axhline(y=30, color='#F44336', linestyle='--', alpha=0.6, linewidth=1, label='Marginal (≥30 dB)')
            ax1.set_ylabel('RxMER (dB)', fontsize=11)
            ax1.grid(True, alpha=0.3)

            # Explicit x-axis limits covering all frequency bands in the data
            if all_plot_freqs:
                ax1.set_xlim(min(all_plot_freqs) - 0.5, max(all_plot_freqs) + 0.5)

            # Build title from assessments
            summary = analysis.summary
            title_lines = [f"US OFDMA RxMER — {summary.num_modems} modem(s), {summary.num_captures} capture(s)"]
            for ma in analysis.modem_assessments:
                parts = [f"{ma.cm_mac_address}: {ma.rxmer_avg_db:.1f} dB avg → {ma.assessment.upper()}"]
                if ma.preeq_assessment:
                    parts.append(f"(pre-eq: {ma.preeq_assessment}, Δ={ma.preeq_delta_avg_db:+.1f} dB)")
                title_lines.append("  " + " ".join(parts))
            ax1.set_title("\n".join(title_lines), fontsize=10)

            # Bottom panel: group stats per frequency band
            ss = analysis.subcarrier_stats
            if ss:
                freqs_ss = [s.frequency_mhz for s in ss]
                means    = [s.mean_db for s in ss]
                stds     = [s.std_db for s in ss]
                bar_w    = (freqs_ss[1] - freqs_ss[0]) if len(freqs_ss) > 1 else 0.05

                # Detect multiple frequency bands in ss (gap > 10 MHz between consecutive points)
                band_breaks = [0]
                for k in range(1, len(freqs_ss)):
                    if freqs_ss[k] - freqs_ss[k - 1] > 10:
                        band_breaks.append(k)
                band_breaks.append(len(freqs_ss))
                multi_band = len(band_breaks) > 2

                # Check for pre-eq delta (single-band, 2-capture case only)
                preeq_pairs = [(ma.preeq_delta_avg_db, ma.cm_mac_address)
                               for ma in analysis.modem_assessments if ma.preeq_delta_avg_db is not None]
                if preeq_pairs and len(captures) == 2 and not multi_band:
                    n_sc = min(len(captures[0].values), len(captures[1].values), len(ss))
                    deltas = [captures[0].values[i] - captures[1].values[i] for i in range(n_sc)]
                    bar_colors = ['#4CAF50' if d > 0 else '#F44336' for d in deltas]
                    ax2.bar(freqs_ss[:n_sc], deltas, width=bar_w, color=bar_colors, alpha=0.7)
                    ax2.axhline(y=0, color='black', linewidth=0.8)
                    ax2.set_ylabel('Δ RxMER (dB)\n(ON−OFF)', fontsize=9)
                    ax2.set_title('Pre-EQ delta: green = pre-eq improves, red = degrades', fontsize=9)
                else:
                    # Plot each band with its own color (one line per frequency band)
                    _band_palette = ['#36A2EB', '#FF6384', '#4CAF50', '#FF9800', '#9C27B0']
                    for b_idx in range(len(band_breaks) - 1):
                        sl = slice(band_breaks[b_idx], band_breaks[b_idx + 1])
                        bf = freqs_ss[sl]
                        bm = means[sl]
                        bs = stds[sl]
                        bc = _band_palette[b_idx % len(_band_palette)]
                        band_label = f"Band {b_idx + 1} mean ({bf[0]:.0f}–{bf[-1]:.0f} MHz)" if multi_band else "Group mean"
                        ax2.plot(bf, bm, color=bc, linewidth=1.5, label=band_label)
                        ax2.fill_between(bf,
                                         [m - s for m, s in zip(bm, bs)],
                                         [m + s for m, s in zip(bm, bs)],
                                         alpha=0.2, color=bc)
                    ax2.set_ylabel('Group RxMER (dB)', fontsize=9)
                    ax2.set_title('Per-subcarrier group statistics', fontsize=9)

            ax2.set_xlabel('Frequency (MHz)', fontsize=11)
            ax2.grid(True, alpha=0.3)

            # Collect all legend handles from both axes and place below the figure
            h1, l1 = ax1.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            all_h, all_l = h1 + h2, l1 + l2
            if all_h:
                fig.legend(all_h, all_l,
                           loc='upper center',
                           bbox_to_anchor=(0.5, 0),
                           ncol=min(len(all_l), 5),
                           fontsize=8, frameon=True)

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
                captures = []
                for e in request.captures:
                    try:
                        captures.append(_load_rxmer_capture(e.filename, request.tftp_path, e.preeq_enabled, e.cm_mac_address, e.ofdma_ifindex))
                    except FileNotFoundError as fnf:
                        self.logger.warning(f"fiberNode/analyze: skipping missing capture {fnf}")
                if not captures:
                    return FiberNodeAnalysis(success=False, error="No capture files found")
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
                captures = []
                for e in request.captures:
                    try:
                        captures.append(_load_rxmer_capture(e.filename, request.tftp_path, e.preeq_enabled, e.cm_mac_address, e.ofdma_ifindex))
                    except FileNotFoundError as fnf:
                        self.logger.warning(f"fiberNode/plot: skipping missing capture {fnf}")
                if not captures:
                    return UsOfdmaRxMerCaptureResponse(success=False, error="No capture files found")
                analysis = _analyze(captures)
                return Response(content=_plot_analysis(analysis), media_type="image/png",
                                headers={"Content-Disposition": "inline; filename=us_rxmer_fibernode.png"})
            except Exception as e:
                self.logger.error(f"fiberNode/plot error: {e}")
                return UsOfdmaRxMerCaptureResponse(success=False, error=str(e))

        # ------------------------------------------------------------------
        # DOCS-IF3-MIB fiber node name resolution
        # Uses shared utilities from fiber_node_utils.py
        # ------------------------------------------------------------------

        async def _resolve_fn_names(svc, ofdma_ifindex_set: set) -> dict:
            """
            Resolve real fiber node names from DOCS-IF3-MIB for all vendors.
            Returns {chIfIndex: fnName} or {} when tables are unavailable.

            Uses shared OID constants and parsing from fiber_node_utils.py.
            """
            def _to_dict(walk_result):
                if not isinstance(walk_result, dict) or not walk_result.get('success'):
                    return None
                raw = walk_result.get('results') or []
                return {item['oid']: item['value']
                        for item in raw if isinstance(item, dict) and 'oid' in item}

            # Map (mdIfIndex, chIfIndex) to channel ID.
            w1_raw = await svc._snmp_walk(OID_MD_CH_CFG_CH_ID, timeout=30)
            d1 = _to_dict(w1_raw)
            self.logger.info(f"FN-resolve CHID walk: success={w1_raw.get('success')}, "
                             f"rows={len(d1) if d1 else 0}, "
                             f"first_oid={next(iter(d1), None) if d1 else None}")
            if not d1:
                self.logger.info(f"FN-resolve: CHID walk empty/failed: {w1_raw.get('error')}")
                return {}

            ifidx_to_md_chid: dict = {}   # chIfIndex → (mdIfIndex, chId)
            pfx1 = OID_MD_CH_CFG_CH_ID + "."
            for oid, val in d1.items():
                if not oid.startswith(pfx1):
                    continue
                parts = oid[len(pfx1):].split('.')
                if len(parts) != 2:
                    continue
                md_if, ch_if = int(parts[0]), int(parts[1])
                if ch_if in ofdma_ifindex_set:
                    ifidx_to_md_chid[ch_if] = (md_if, int(str(val).strip()))

            self.logger.info(f"FN-resolve: matched {len(ifidx_to_md_chid)}/{len(d1)} MdChCfg rows "
                             f"(ofdma set size={len(ofdma_ifindex_set)}, "
                             f"sample ifidx={list(ofdma_ifindex_set)[:2]})")
            if not ifidx_to_md_chid:
                return {}

            # Resolve fiber-node names from string-indexed OIDs.
            w4_raw = await svc._snmp_walk(OID_MD_NODE_STATUS_MD_US_SG_ID, timeout=30)
            d4 = _to_dict(w4_raw)
            self.logger.info(f"FN-resolve FNSG walk: success={w4_raw.get('success')}, "
                             f"rows={len(d4) if d4 else 0}, error={w4_raw.get('error')}")
            if not d4:
                return {}

            ussg_to_fn: dict = {}   # (mdIfIndex, mUSsgId) → fnName
            for oid, val in d4.items():
                parsed = parse_fn_name_from_oid(oid, OID_MD_NODE_STATUS_MD_US_SG_ID)
                if parsed:
                    fn_name, md_if, _ = parsed
                    m_us_sg = int(str(val).strip())  # value is mUSsgId
                    ussg_to_fn.setdefault((md_if, m_us_sg), fn_name)

            self.logger.info(f"FN-resolve: {len(ussg_to_fn)} FN names decoded: "
                             f"{dict(list(ussg_to_fn.items())[:5])}")
            if not ussg_to_fn:
                return {}

            # ── Step 3: (mdIfIndex, mUSsgId) → chSetId ─────────────────────
            pfx3 = OID_MD_US_SG_STATUS_CH_SET_ID + "."
            d3 = _to_dict(await svc._snmp_walk(OID_MD_US_SG_STATUS_CH_SET_ID, timeout=30))
            if not d3:
                self.logger.warning("FN-resolve: SGSET walk empty/failed")
                return {}

            ussg_to_chset: dict = {}   # (mdIfIndex, mUSsgId) → chSetId
            for oid, val in d3.items():
                if not oid.startswith(pfx3):
                    continue
                parts = oid[len(pfx3):].split('.')
                if len(parts) != 2:
                    continue
                ussg_to_chset[(int(parts[0]), int(parts[1]))] = int(str(val).strip())

            self.logger.info(f"FN-resolve: {len(ussg_to_chset)} mUSsgId→chSetId entries")

            # ── Step 4: (mdIfIndex, chSetId) → frozenset of chIds (shared parse_channel_id_list)
            pfx2 = OID_US_CH_SET_CH_LIST + "."
            w2_raw = await svc._snmp_walk(OID_US_CH_SET_CH_LIST, timeout=30)
            d2 = _to_dict(w2_raw)
            self.logger.info(f"FN-resolve CHLST walk: success={w2_raw.get('success')}, "
                             f"rows={len(d2) if d2 else 0}, error={w2_raw.get('error')}, "
                             f"sample_oid={next(iter(d2), None) if d2 else None}, "
                             f"sample_val={next(iter(d2.values()), None) if d2 else None}")
            if not d2:
                self.logger.warning("FN-resolve: CHLST walk empty/failed")
                return {}

            chset_chids: dict = {}   # (mdIfIndex, chSetId) → frozenset of chIds
            _parse_warn_done = False
            for oid, val in d2.items():
                if not oid.startswith(pfx2):
                    continue
                parts = oid[len(pfx2):].split('.')
                if len(parts) != 2:
                    continue
                chids = parse_channel_id_list(val)   # shared utility
                if chids:
                    chset_chids[(int(parts[0]), int(parts[1]))] = chids
                elif not _parse_warn_done:
                    self.logger.warning(f"FN-resolve: parse_channel_id_list empty for val={repr(val)}")
                    _parse_warn_done = True

            self.logger.info(f"FN-resolve: {len(chset_chids)} chSetId→chIds entries, "
                             f"sample: {dict(list(chset_chids.items())[:2])}")

            # ── Compose: chIfIndex → fnName ─────────────────────────────────
            result: dict = {}
            _unresolved = []
            for ch_if, (md_if, ch_id) in ifidx_to_md_chid.items():
                found = False
                for (md2, m_us_sg), chset_id in ussg_to_chset.items():
                    if md2 != md_if:
                        continue
                    if ch_id not in chset_chids.get((md_if, chset_id), frozenset()):
                        continue
                    fn_name = ussg_to_fn.get((md_if, m_us_sg))
                    if fn_name:
                        result[ch_if] = fn_name
                    found = True
                    break
                if not found:
                    _unresolved.append((ch_if, md_if, ch_id))

            if _unresolved:
                self.logger.warning(
                    f"FN-resolve: {len(_unresolved)}/{len(ifidx_to_md_chid)} channels unresolved. "
                    f"Sample: {_unresolved[:5]}. "
                    f"ussg_to_chset keys(sample): {list(ussg_to_chset.keys())[:5]}, "
                    f"chset_chids keys(sample): {list(chset_chids.keys())[:5]}"
                )
            self.logger.info(f"FN-resolve: mapped {len(result)}/{len(ifidx_to_md_chid)} channels to FN names")
            return result

        @self.router.get(
            "/channel/list",
            summary="List all OFDMA upstream channels on a CMTS",
        )
        async def get_channel_list(
            cmts_ip: str,
            community: str = "public",
            refresh: bool = False,
        ):
            """
            Walk ifDescr + DOCS-IF3-MIB fiber node tables to return all OFDMA
            upstream interfaces grouped by real fiber node name.
            Falls back to ifDescr-derived grouping when DOCS-IF3-MIB tables
            are unavailable (non-standard vendors).
            Results are cached in MySQL (5 min default). Pass refresh=true to force SNMP re-walk.
            """
            # ── 1. In-memory cache ──────────────────────────────────────
            mem_cache = UsOfdmaRxMerRouter._channel_list_cache
            if not refresh and cmts_ip in mem_cache:
                ts, cached_result = mem_cache[cmts_ip]
                age = time.time() - ts
                if age < UsOfdmaRxMerRouter._CHANNEL_LIST_TTL:
                    self.logger.info(f"channel/list memory-cache hit for {cmts_ip} (age={age:.0f}s)")
                    return {**cached_result, "_cached": True, "_cache_age_s": round(age)}

            # ── 2. MySQL cache ──────────────────────────────────────────
            if not refresh:
                try:
                    from pypnm.api.routes.topology.service import topology_service
                    db_result = topology_service.storage.get_cached_fiber_nodes(cmts_ip, max_age_s=UsOfdmaRxMerRouter._CHANNEL_LIST_TTL)
                    if db_result:
                        self.logger.info(f"channel/list DB-cache hit for {cmts_ip}")
                        mem_cache[cmts_ip] = (time.time(), db_result)
                        return db_result
                except Exception as _db_err:
                    self.logger.debug(f"DB cache lookup failed (non-fatal): {_db_err}")

            # ── 3. Live SNMP walk ───────────────────────────────────────
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
                    # Commscope E6000:  "cable-us-ofdma 1/ofd/32.0"
                    # Commscope EVO:    "RPHY OFDMA Upstream 5:0/0.0/0"
                    # Commscope SC-QAM: "cable-upstream 1/scq/7", "1/nd/7", "1/0/7" → excluded (no 'us-ofdma')
                    # Cisco OFDMA:      "Cable1/0/0-upstream0"  (capital C + hyphen-upstream)
                    # Casa OFDMA:       "OFDMA Upstream 0/6.0" (where modems actually register)
                    # Casa Logical:     "Logical Upstream Channel 0/0.0/0" (deprecated, excluded)
                    # Casa SC-QAM:      "Upstream Physical Interface 0/0.0" → excluded
                    is_commscope_ofdma = 'us-ofdma' in lower
                    is_commscope_evo   = lower.startswith('rphy ofdma upstream')
                    is_cisco_ofdma     = desc.startswith('Cable') and '-upstream' in lower
                    is_casa_ofdma      = lower.startswith('ofdma upstream')
                    if not (is_commscope_ofdma or is_commscope_evo or is_cisco_ofdma or is_casa_ofdma):
                        continue
                    try:
                        ifindex = int(str(oid).rsplit('.', 1)[-1])
                    except ValueError:
                        continue
                    # Fallback MAC-domain grouping (used when DOCS-IF3-MIB unavailable):
                    # Commscope E6000: "cable-us-ofdma 1/ofd/32.0" → "cable-mac 1"
                    # Commscope EVO:   "RPHY OFDMA Upstream 5:0/0.0/0" → "RPD-5:0"
                    # Cisco:           "Cable1/0/0-upstream0"        → "Cable1/0/0"
                    # Casa:            "OFDMA Upstream 0/6.0" → "OFDMA-0"
                    m_arris = _re.match(r'cable-us-ofdma\s+(\d+)/', desc, _re.IGNORECASE)
                    m_evo   = _re.match(r'RPHY\s+OFDMA\s+Upstream\s+(\d+:\d+)/', desc, _re.IGNORECASE)
                    m_casa  = _re.match(r'OFDMA\s+Upstream\s+(\d+)/', desc, _re.IGNORECASE)
                    if m_arris:
                        fallback_md = f"cable-mac {m_arris.group(1)}"
                    elif m_evo:
                        fallback_md = f"RPD-{m_evo.group(1)}"
                    elif m_casa:
                        fallback_md = f"OFDMA-{m_casa.group(1)}"
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

                # ── Get modem counts per channel ────────────────────────────
                # Walk docsIf31CmtsCmUsOfdmaChannelStatus to count modems per OFDMA channel
                # OID: 1.3.6.1.4.1.4491.2.1.28.1.4.1.2 — indexed by (cm_index, ofdma_ifindex)
                # This is the DOCSIS 3.1 OFDMA-specific table (not the D3.0 SC-QAM table!)
                OID_CM_OFDMA_STATUS = "1.3.6.1.4.1.4491.2.1.28.1.4.1.2"
                modem_counts: dict = {ch['ifindex']: 0 for ch in channels}
                # Track unique cm_index per mac_domain to avoid double-counting
                # modems that appear on multiple channels of the same fiber node.
                ifidx_to_domain = {ch['ifindex']: ch['mac_domain'] for ch in channels}
                domain_unique_cms: dict = {}   # mac_domain -> set of cm_index
                try:
                    cm_walk = await service._snmp_walk(OID_CM_OFDMA_STATUS, timeout=30)
                    self.logger.info(f"CM OFDMA walk: success={cm_walk.get('success') if isinstance(cm_walk, dict) else False}, "
                                     f"results={len(cm_walk.get('results', [])) if isinstance(cm_walk, dict) else 0}")
                    if isinstance(cm_walk, dict) and cm_walk.get('success'):
                        cm_raw = cm_walk.get('results') or []
                        matched = 0
                        seen_ifidx: set = set()
                        for item in cm_raw:
                            if isinstance(item, dict) and 'oid' in item:
                                try:
                                    # OID ends with cm_index.ofdma_ifindex
                                    oid = str(item['oid'])
                                    parts = oid.rstrip('.').split('.')
                                    ifidx    = int(parts[-1])   # last element is ofdma_ifindex
                                    cm_index = int(parts[-2])   # second-to-last is cm_index
                                    seen_ifidx.add(ifidx)
                                    if ifidx in modem_counts:
                                        modem_counts[ifidx] += 1
                                        matched += 1
                                    # Track unique cm per fiber node (mac_domain)
                                    domain = ifidx_to_domain.get(ifidx)
                                    if domain is not None:
                                        domain_unique_cms.setdefault(domain, set()).add(cm_index)
                                except (ValueError, IndexError):
                                    pass
                        self.logger.info(f"CM OFDMA walk matched {matched}/{len(cm_raw)} entries, "
                                         f"ofdma_ifidx sample: {list(modem_counts.keys())[:3]}, "
                                         f"cm_ifidx sample: {list(seen_ifidx)[:5]}")
                except Exception as _cm_err:
                    self.logger.warning(f"Modem count walk failed: {_cm_err}")

                # Add modem_count to each channel
                for ch in channels:
                    ch['modem_count'] = modem_counts.get(ch['ifindex'], 0)

                channels.sort(key=lambda c: c['description'])
                seen: dict = {}
                for ch in channels:
                    md = ch['mac_domain']
                    if md not in seen:
                        seen[md] = {"name": ch['suggested_fn'], "mac_domain": md, "channels": [], "modem_count": 0}
                    seen[md]['channels'].append({"ifindex": ch['ifindex'], "description": ch['description'], "modem_count": ch['modem_count']})
                # Use unique-modem count per fiber node (not per-channel sum)
                for md, fn_data in seen.items():
                    fn_data['modem_count'] = len(domain_unique_cms.get(md, set()))

                # Always exclude fallback mac-domain entries — only show
                # real FN names from DOCS-IF3-MIB resolution.
                _fallback_prefixes = ('cable-mac', 'OFDMA-', 'RPD-', 'FN-cable-mac', 'FN-OFDMA-', 'FN-RPD-', 'Cable')

                result = {
                    "success":     True,
                    "channels":    channels,
                    "fiber_nodes": sorted([
                        f for f in seen.values()
                        if f['modem_count'] > 0
                        and not f['mac_domain'].startswith(_fallback_prefixes)
                    ], key=lambda f: f['mac_domain']),
                }

                # ── Store in MySQL + memory cache ───────────────────────
                mem_cache[cmts_ip] = (time.time(), result)
                try:
                    from pypnm.api.routes.topology.service import topology_service
                    topology_service.storage.store_fiber_node_cache(
                        cmts_ip, result["channels"], result["fiber_nodes"],
                    )
                    self.logger.info(f"channel/list stored in DB cache for {cmts_ip}")
                except Exception as _store_err:
                    self.logger.debug(f"DB cache store failed (non-fatal): {_store_err}")

                return result
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
            Walk docsIf31CmtsCmUsOfdmaChannelStatus to find all CMs on a given
            OFDMA upstream ifIndex, then get their MAC from
            docsIf3CmtsCmRegStatusMacAddr.
            Returns [{cm_mac_address, cm_index}].
            """
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=cmts_ip, community=community, write_community=community
            )
            try:
                # docsIf31CmtsCmUsOfdmaChannelStatus  1.3.6.1.4.1.4491.2.1.28.1.4.1.2
                # OID index: {cm_index}.{ofdma_ifindex} — DOCSIS 3.1 OFDMA specific!
                OID_CM_OFDMA_STATUS = "1.3.6.1.4.1.4491.2.1.28.1.4.1.2"
                # docsIfCmtsCmStatusMacAddress  1.3.6.1.2.1.10.127.1.3.3.1.2
                # index: {cm_index}  value: MAC as 6 hex octets  (works on E6000/Commscope)
                OID_CM_REG_MAC = "1.3.6.1.2.1.10.127.1.3.3.1.2"

                walk = await service._snmp_walk(OID_CM_OFDMA_STATUS)
                if not isinstance(walk, dict) or not walk.get('success'):
                    return {"success": False, "error": walk.get('error', 'SNMP walk failed'), "modems": []}

                # agent returns {'results': [{oid, value, type}, ...]} (list)
                raw = walk.get('results') or []
                if isinstance(raw, list):
                    oid_list = [item['oid'] for item in raw if isinstance(item, dict) and 'oid' in item]
                elif isinstance(raw, dict):
                    oid_list = list(raw.keys())
                else:
                    oid_list = []

                matching_cm_idx: set = set()
                for oid in oid_list:
                    try:
                        # OID ends with cm_index.ofdma_ifindex
                        parts = str(oid).rstrip('.').split('.')
                        ifidx = int(parts[-1])   # last element is ofdma_ifindex
                        cm_idx = int(parts[-2])  # second-to-last is cm_index
                        if ifidx == ofdma_ifindex:
                            matching_cm_idx.add(cm_idx)
                    except (ValueError, IndexError):
                        continue

                modems = []
                for cm_idx in list(matching_cm_idx)[:max_modems]:
                    mac_result = await service._snmp_get(f"{OID_CM_REG_MAC}.{cm_idx}")
                    if not mac_result.get('success'):
                        continue
                    raw = service._parse_get_value(mac_result) or ""
                    # Handle various MAC formats:
                    #  - '0x90324bc813df' (hex string from agent)
                    #  - 'D4 6A 6A FD 00 B3' (space-separated hex)
                    #  - 'aa:bb:cc:dd:ee:ff' (already formatted)
                    hex_str = raw.replace("0x", "").replace(" ", "").replace(":", "").strip()
                    if len(hex_str) == 12:
                        mac = ":".join(hex_str[i:i+2].lower() for i in range(0, 12, 2))
                        modems.append({"cm_mac_address": mac, "cm_index": cm_idx})

                return {"success": True, "ofdma_ifindex": ofdma_ifindex, "modems": modems}
            except Exception as e:
                self.logger.error(f"channel/modems error: {e}")
                return {"success": False, "error": str(e), "modems": []}
            finally:
                service.close()


# Required for dynamic auto-registration
router = UsOfdmaRxMerRouter().router
