# PyPNM Channel Stats API Router
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Optimized channel statistics endpoint using parallel bulk walks via agent.

This endpoint returns comprehensive DS/US channel information:
- DS SC-QAM: frequency, power, SNR, RxMER, modulation, FEC stats
- DS OFDM: PLC frequency, power, MER, subcarrier info (DOCSIS 3.1)
- US ATDMA: frequency, width, TX power, T3/T4 timeouts, type
- US OFDMA: frequency, TX power, subcarrier info (DOCSIS 3.1)

Performance: ~8-10 seconds via parallel bulk walks (vs ~60+ seconds sequential)
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pypnm.api.routes.common.service.fiber_node_utils import (
    OID_MD_NODE_STATUS_MD_DS_SG_ID,
    parse_fn_name_from_oid_by_sg_id,
)

# In-process cache: (cmts_ip, mac) -> (cm_index, expires_at)
_CM_INDEX_CACHE: dict = {}
_CM_INDEX_TTL = 3600  # 1 hour


def _get_cached_cm_index(cmts_ip: str, mac: str):
    key = (cmts_ip, mac.lower())
    entry = _CM_INDEX_CACHE.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


def _set_cached_cm_index(cmts_ip: str, mac: str, cm_index: int):
    key = (cmts_ip, mac.lower())
    _CM_INDEX_CACHE[key] = (cm_index, time.time() + _CM_INDEX_TTL)

from pypnm.api.agent.manager import get_agent_manager
from .parser import parse_channel_stats_raw

logger = logging.getLogger(__name__)


class ChannelStatsRequest(BaseModel):
    """Request model for channel stats."""
    mac_address: str = Field(..., description="Cable modem MAC address")
    modem_ip: str = Field(..., description="Cable modem IP address")
    community: str = Field(default="public", description="SNMP community string")
    cmts_ip: Optional[str] = Field(default=None, description="CMTS IP address for fiber node lookup")
    cmts_community: Optional[str] = Field(default=None, description="CMTS SNMP community string")
    cm_index: Optional[int] = Field(default=None, description="Known CM registration index on CMTS (skip MAC walk)")
    skip_connectivity_check: bool = Field(default=False, description="Skip ping/SNMP check")
    cmts_stats: bool = Field(default=False, description="Fetch CMTS-side OFDMA MeanRxMer and IUC profile stats (slower)")
    experimental_compact_walk: bool = Field(
        default=False,
        description="Use compact SNMP roots and rebucket results into table-specific parser format"
    )
    cmts_task_timeout_s: float = Field(
        default=30.0,
        description="Timeout (seconds) for CMTS-side SNMP walk tasks"
    )


class ChannelStatsResponse(BaseModel):
    """Response model for channel stats."""
    success: bool
    status: int = 0
    mac_address: Optional[str] = None
    modem_ip: Optional[str] = None
    fiber_node: Optional[str] = None
    timestamp: Optional[str] = None
    timing: Optional[dict] = None
    downstream: Optional[dict] = None
    upstream: Optional[dict] = None
    ofdm_stats: Optional[dict] = None
    error: Optional[str] = None


class ChannelStatsRouter:
    """
    FastAPI router for optimized channel statistics endpoint.
    
    Uses parallel bulk walks via remote agent for fast data collection (~8-10s).
    """
    
    def __init__(
        self,
        prefix: str = "/cm/channel-stats",
        tags: list[str | Enum] = None
    ) -> None:
        if tags is None:
            tags = ["Cable Modem Channel Stats"]
        self.router = APIRouter(prefix=prefix, tags=tags)
        self.logger = logging.getLogger(__name__)
        # Ensure logger level is set to INFO
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        self._register_routes()
    
    def _register_routes(self) -> None:
        @self.router.post(
            "",
            response_model=ChannelStatsResponse,
            summary="Get Cable Modem Channel Statistics",
            description="Fetch comprehensive DS/US channel stats using optimized parallel bulk walks.",
        )
        async def get_channel_stats(request: ChannelStatsRequest) -> ChannelStatsResponse:
            """
            Get comprehensive channel statistics for a cable modem.
            
            Uses optimized parallel bulk walks via the remote agent for fast data collection.
            
            Tables walked in parallel:
            - docsIfDownChannelTable: DS SC-QAM freq, power, modulation
            - docsIfSigQTable: DS SC-QAM SNR, codewords
            - docsIf3SignalQualityExtTable: DS SC-QAM RxMER
            - docsIf31CmDsOfdmChanTable: DS OFDM (DOCSIS 3.1)
            - docsIfUpChannelTable: US ATDMA freq, width, type
            - docsIf3CmStatusUsTable: US ATDMA TX power, T3 timeouts
            - docsIf31CmUsOfdmaChanTable: US OFDMA (DOCSIS 3.1)
            
            Returns:
                ChannelStatsResponse with DS/US channel data
            """
            agent_manager = get_agent_manager()
            if not agent_manager:
                raise HTTPException(status_code=503, detail="Agent manager not initialized")
            
            # Route modem-side tasks to a CM-reachable agent.
            cm_agent_id = agent_manager.get_agent_id_for_capability('cm_reachable')
            if not cm_agent_id:
                raise HTTPException(status_code=503, detail="No cm_reachable agent available")

            # Route CMTS-side tasks (OFDMA MeanRxMer, fiber-node lookup) to a
            # CMTS-reachable agent when CMTS context is provided.
            cmts_agent_id = None
            if request.cmts_ip:
                cmts_agent_id = agent_manager.get_agent_id_for_capability('cmts_reachable')
                if not cmts_agent_id:
                    self.logger.warning(
                        f"No cmts_reachable agent available for CMTS {request.cmts_ip}; "
                        "CMTS-side enrichments will be skipped"
                    )
            
            self.logger.info(
                f"Getting channel stats for {request.modem_ip} via cm_agent={cm_agent_id} "
                f"cmts_agent={cmts_agent_id or 'none'}"
            )
            
            try:
                cmts_task_timeout = max(10.0, min(float(request.cmts_task_timeout_s), 90.0))

                # Define canonical table OIDs expected by parser.
                canonical_table_oids = [
                    '1.3.6.1.2.1.10.127.1.1.1',     # docsIfDownChannelTable
                    '1.3.6.1.2.1.10.127.1.1.4',     # docsIfSigQTable
                    '1.3.6.1.4.1.4491.2.1.20.1.24', # docsIf3SignalQualityExtTable
                    '1.3.6.1.4.1.4491.2.1.28.1.9',  # docsIf31CmDsOfdmChanTable
                    '1.3.6.1.4.1.4491.2.1.28.1.11', # docsIf31CmDsOfdmChannelPowerTable
                    '1.3.6.1.4.1.4491.2.1.28.1.2',  # docsIf31RxChStatusTable (OFDM profiles)
                    '1.3.6.1.4.1.4491.2.1.28.1.10', # docsIf31CmDsOfdmProfileStatsTable (OFDM codewords)
                    '1.3.6.1.2.1.10.127.1.1.2',     # docsIfUpChannelTable
                    '1.3.6.1.4.1.4491.2.1.20.1.2',  # docsIf3CmStatusUsTable
                    '1.3.6.1.4.1.4491.2.1.28.1.13', # docsIf31CmUsOfdmaChanTable
                    '1.3.6.1.4.1.4491.2.1.28.1.12', # docsIf31CmStatusOfdmaUsTable
                    '1.3.6.1.4.1.4491.2.1.28.1.14', # docsIf31CmUsOfdmaProfileStatsTable (OFDMA IUC stats)
                    '1.3.6.1.4.1.4491.2.1.27.1.2.5', # docsPnmCmDsOfdmRxMerTable (OFDM DS MER mean)
                ]

                # Experimental compact mode: fewer roots can be faster on some CMTS,
                # but still requires parser-compatible rebucketing.
                if request.experimental_compact_walk:
                    table_oids = [
                        '1.3.6.1.2.1.10.127.1.1',      # docsIf root
                        '1.3.6.1.4.1.4491.2.1.20.1',   # docsIf3 root
                        '1.3.6.1.4.1.4491.2.1.28.1',   # docsIf31 root
                        '1.3.6.1.4.1.4491.2.1.27.1.2.5',
                    ]
                else:
                    table_oids = canonical_table_oids
                
                # Send parallel walk task to agent
                import time
                start_time = time.time()
                
                # Do connectivity check first if not skipped
                if not request.skip_connectivity_check:
                    # Quick SNMP check
                    check_task_id = await agent_manager.send_task(
                        cm_agent_id, "snmp_get",
                        {"target_ip": request.modem_ip, "oid": "1.3.6.1.2.1.1.1.0", "community": request.community},
                        timeout=5.0
                    )
                    check_result = await agent_manager.wait_for_task_async(check_task_id, timeout=5.0)
                    if not check_result or not check_result.get("result", {}).get("success"):
                        return ChannelStatsResponse(
                            success=False,
                            status=-1,
                            error="SNMP not responding on modem"
                        )
                
                # Send modem parallel walk task.
                # Cable modems have few rows per table (<50), so use small
                # max_repetitions (25 vs agent default 500) and short PDU
                # timeout (3s) to avoid bloated GetBulk requests that stall
                # the modem's SNMP agent.
                task_id = await agent_manager.send_task(
                    cm_agent_id,
                    "snmp_parallel_walk",
                    {
                        "ip": request.modem_ip,
                        "oids": table_oids,
                        "community": request.community,
                        "timeout": 3,
                        "max_repetitions": 25,
                    },
                    timeout=90.0
                )

                # Concurrently send CMTS OFDMA walk + fiber node lookup tasks
                # (Cisco modems return empty modem-side OFDMA; CMTS walk runs in
                # parallel so it adds zero extra wall-clock time)
                cmts_ofdma_task_id = None
                cmts_rxmer_task_id = None
                cmts_cmindex_task_id = None
                cmts_chanid_task_id = None
                cmts_profile_task_id = None
                fiber_node_sg_task_id = None
                cmts_partial_reason_task_id = None
                cmts_us_iuc_stats_task_id = None
                cmts_ds_ofdm_speed_task_id = None
                cmts_ds_subcarrier_task_id = None
                cmts_ifname_task_id = None
                cached_cm_index = None
                if request.cmts_ip and request.mac_address and cmts_agent_id:
                    if request.cm_index is not None:
                        try:
                            cached_cm_index = int(request.cm_index)
                            _set_cached_cm_index(request.cmts_ip, request.mac_address, cached_cm_index)
                            self.logger.info(f"Using provided cm_index={cached_cm_index} for {request.mac_address}")
                        except (ValueError, TypeError):
                            cached_cm_index = None

                    if cached_cm_index is None:
                        cached_cm_index = _get_cached_cm_index(request.cmts_ip, request.mac_address)
                    if cached_cm_index is not None:
                        # Fast path: direct snmpget for SG ID using known cm_index (runs in parallel with modem walk)
                        try:
                            fiber_node_sg_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_get",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.20.1.3.1.8.{cached_cm_index}',
                                    "community": request.cmts_community or "public",
                                },
                                timeout=5.0,
                            )
                        except Exception as e:
                            self.logger.debug(f"Fiber node pre-task failed: {e}")
                    else:
                        # No cached cm_index — send MAC table walk to resolve it
                        # in parallel with modem walks (avoids 30s fallback later)
                        try:
                            cmts_cmindex_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": '1.3.6.1.4.1.4491.2.1.20.1.3.1.2',  # docsIf3CmtsCmRegStatusMacAddr
                                    "community": request.cmts_community or "public",
                                },
                                timeout=cmts_task_timeout,
                            )
                        except Exception as e:
                            self.logger.debug(f"cm_index pre-task failed: {e}")

                if request.cmts_ip and request.cmts_stats and cmts_agent_id:
                    try:
                        if cached_cm_index is None:
                            cmts_ofdma_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": '1.3.6.1.4.1.4491.2.1.28.1.4',
                                    "community": request.cmts_community or "public",
                                },
                                timeout=cmts_task_timeout,
                            )
                        if cached_cm_index is not None:
                            # Scoped walks — tiny, fast
                            cmts_rxmer_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.28.1.4.1.2.{cached_cm_index}',
                                    "community": request.cmts_community or "public",
                                },
                                timeout=cmts_task_timeout,
                            )
                            cmts_profile_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.28.1.5.1.1.{cached_cm_index}',
                                    "community": request.cmts_community or "public",
                                },
                                timeout=cmts_task_timeout,
                            )
                        else:
                            # Full walks + MAC walk to resolve cm_index
                            cmts_rxmer_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": '1.3.6.1.4.1.4491.2.1.28.1.4.1.2',
                                    "community": request.cmts_community or "public",
                                },
                                timeout=cmts_task_timeout,
                            )
                            # cmts_cmindex_task_id already dispatched in the
                            # outer block above; reuse it, don't send again.
                            cmts_profile_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": '1.3.6.1.4.1.4491.2.1.28.1.5.1.1',
                                    "community": request.cmts_community or "public",
                                },
                                timeout=cmts_task_timeout,
                            )
                        # Partial service reason codes.
                        # When cm_index is already known, walk only this modem's rows (tiny).
                        # Otherwise walk the full col-1 subtree; the parser will filter by
                        # the cm_index that gets resolved later from the MAC walk.
                        if cached_cm_index is not None:
                            _partial_oid = f'1.3.6.1.4.1.4491.2.1.28.1.7.1.1.{cached_cm_index}'
                        else:
                            _partial_oid = '1.3.6.1.4.1.4491.2.1.28.1.7.1.1'
                        cmts_partial_reason_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": _partial_oid,
                                "community": request.cmts_community or "public",
                            },
                            timeout=cmts_task_timeout,
                        )
                        # New: US OFDMA IUC stats (per-channel aggregate, small table)
                        cmts_us_iuc_stats_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.24',
                                "community": request.cmts_community or "public",
                            },
                            timeout=cmts_task_timeout,
                        )
                        # New: DS OFDM profile speed per channel+profile
                        cmts_ds_ofdm_speed_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.20',
                                "community": request.cmts_community or "public",
                            },
                            timeout=cmts_task_timeout,
                        )
                        # New: DS OFDM subcarrier status (modulation per range)
                        cmts_ds_subcarrier_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.21',
                                "community": request.cmts_community or "public",
                            },
                            timeout=cmts_task_timeout,
                        )
                        # ifName table — maps ifIndex → interface name (e.g. Cable8/0/0)
                        cmts_ifname_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.2.1.31.1.1.1.1',
                                "community": request.cmts_community or "public",
                            },
                            timeout=cmts_task_timeout,
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to send CMTS OFDMA task: {e}")

                # Wait for modem walk result (13 OIDs walked sequentially;
                # typical: 2-4s each = 30-50s total)
                result = await agent_manager.wait_for_task_async(task_id, timeout=90.0)

                if not result:
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error="Agent task timed out"
                    )

                # Handle top-level error/timeout from manager (no 'result' envelope)
                if 'result' not in result:
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error=result.get('error', 'Agent returned no result')
                    )

                # Extract raw SNMP walk results
                agent_result = result.get("result", {})
                walk_warnings = agent_result.get("warnings", [])
                if not agent_result.get("success"):
                    err = agent_result.get("error") or "SNMP walk failed — all OID trees empty (wrong community or modem offline)"
                    if walk_warnings:
                        err = f"{err} | warnings: {'; '.join(walk_warnings[:3])}"
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error=err
                    )

                raw_results = agent_result.get("results", {})

                # Log per-OID walk durations returned by the agent (if available)
                walk_durations = agent_result.get("walk_durations", {})
                if walk_durations:
                    # Build human-readable OID name mapping
                    oid_names = {v: k for k, v in {
                        'DownCh': '1.3.6.1.2.1.10.127.1.1.1',
                        'SigQ': '1.3.6.1.2.1.10.127.1.1.4',
                        'RxMER': '1.3.6.1.4.1.4491.2.1.20.1.24',
                        'DsOFDM': '1.3.6.1.4.1.4491.2.1.28.1.9',
                        'DsOFDMPow': '1.3.6.1.4.1.4491.2.1.28.1.11',
                        'RxChStat': '1.3.6.1.4.1.4491.2.1.28.1.2',
                        'DsOFDMProf': '1.3.6.1.4.1.4491.2.1.28.1.10',
                        'UpCh': '1.3.6.1.2.1.10.127.1.1.2',
                        'UsStatus': '1.3.6.1.4.1.4491.2.1.20.1.2',
                        'UsOFDMA': '1.3.6.1.4.1.4491.2.1.28.1.13',
                        'UsOFDMAStat': '1.3.6.1.4.1.4491.2.1.28.1.12',
                        'UsOFDMAProf': '1.3.6.1.4.1.4491.2.1.28.1.14',
                        'PnmRxMer': '1.3.6.1.4.1.4491.2.1.27.1.2.5',
                    }.items()}
                    dur_parts = sorted(walk_durations.items(), key=lambda x: -x[1])
                    dur_str = ' | '.join(
                        f"{oid_names.get(oid, oid.split('.')[-1])}={dur}s({len(raw_results.get(oid, []))})"
                        for oid, dur in dur_parts
                    )
                    total_walk = sum(walk_durations.values())
                    self.logger.info(
                        f"Per-OID walk durations for {request.modem_ip}: "
                        f"total={total_walk:.1f}s | {dur_str}"
                    )

                if request.experimental_compact_walk:
                    # Convert compact-root walk output into parser's canonical
                    # per-table result map: {table_oid: [entries...]}
                    normalized = {oid: [] for oid in canonical_table_oids}

                    # Preserve exact-key results when available.
                    for oid in canonical_table_oids:
                        if oid in raw_results and isinstance(raw_results.get(oid), list):
                            normalized[oid].extend(raw_results.get(oid) or [])

                    # Rebucket entries from broader roots by longest matching
                    # canonical table prefix.
                    for root_oid, entries in raw_results.items():
                        if root_oid in canonical_table_oids or not isinstance(entries, list):
                            continue
                        for entry in entries:
                            oid = str(entry.get('oid', ''))
                            best = None
                            for t_oid in canonical_table_oids:
                                if oid.startswith(t_oid + '.') or oid == t_oid:
                                    if best is None or len(t_oid) > len(best):
                                        best = t_oid
                            if best:
                                normalized[best].append(entry)

                    raw_results = normalized
                walk_time = time.time() - start_time

                async def _safe_wait_task(task_id: Optional[str], timeout: float):
                    if not task_id:
                        return None
                    try:
                        return await agent_manager.wait_for_task_async(task_id, timeout=timeout)
                    except Exception as wait_err:
                        self.logger.debug(f"Task wait failed for {task_id}: {wait_err}")
                        return None

                # Await CMTS tasks concurrently so slow paths don't add linearly.
                (
                    cmts_ofdma_result,
                    cmts_cmindex_result,
                    cmts_rxmer_result,
                    cmts_profile_result,
                    cmts_partial_reason_result,
                    cmts_us_iuc_stats_result,
                    cmts_ds_ofdm_speed_result,
                    cmts_ds_subcarrier_result,
                    cmts_ifname_result,
                ) = await asyncio.gather(
                    _safe_wait_task(cmts_ofdma_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_cmindex_task_id, max(cmts_task_timeout, 45.0)),  # MAC table is large (~9k entries, ~33s)
                    _safe_wait_task(cmts_rxmer_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_profile_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_partial_reason_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_us_iuc_stats_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ds_ofdm_speed_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ds_subcarrier_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ifname_task_id, cmts_task_timeout),
                )

                cmts_cmindex_timed_out = bool(
                    cmts_cmindex_task_id
                    and isinstance(cmts_cmindex_result, dict)
                    and 'timeout' in str(cmts_cmindex_result.get('error', '')).lower()
                )

                # Collect CMTS OFDMA result (already running in parallel)
                ofdma_oid = '1.3.6.1.4.1.4491.2.1.28.1.13'
                modem_ofdma_empty = not raw_results.get(ofdma_oid)
                if modem_ofdma_empty and cmts_ofdma_result:
                    try:
                        cmts_result = cmts_ofdma_result
                        if cmts_result and cmts_result.get("result", {}).get("success"):
                            cmts_ofdma_entries = cmts_result.get("result", {}).get("results", [])
                            if cmts_ofdma_entries:
                                raw_results[ofdma_oid] = cmts_ofdma_entries
                                self.logger.info(
                                    f"Injected {len(cmts_ofdma_entries)} CMTS OFDMA entries "
                                    f"(Cisco fallback, ran in parallel)"
                                )
                    except Exception as cmts_ofdma_err:
                        self.logger.warning(f"CMTS OFDMA fallback failed: {cmts_ofdma_err}")

                # Parse results in API (NOT in agent)
                parsed = parse_channel_stats_raw(
                    raw_results, walk_time, request.mac_address, request.modem_ip
                )

                # Collect CMTS OFDMA MeanRxMer and inject into parsed channels
                # First: resolve cm_index (needed for both rxmer and fiber node)
                cm_index = cached_cm_index
                if cmts_cmindex_result and cm_index is None and request.mac_address:
                    try:
                        cmidx_result = cmts_cmindex_result
                        inner = cmidx_result.get('result', {})
                        if inner.get('success'):
                            entries = inner.get('results', [])
                            mac_clean = request.mac_address.replace(':', '').replace('-', '').lower()
                            for entry in entries:
                                val = entry.get('value', '')
                                if isinstance(val, str):
                                    entry_mac = val.replace('0x', '').replace(' ', '').replace(':', '').replace('-', '').lower()
                                    if entry_mac == mac_clean:
                                        oid = entry.get('oid', '')
                                        suffix = oid.split('1.3.6.1.4.1.4491.2.1.20.1.3.1.2.')[-1]
                                        try:
                                            cm_index = int(suffix.strip('.'))
                                        except ValueError:
                                            pass
                                        break
                        if cm_index is not None:
                            self.logger.info(f'Resolved cm_index={cm_index} for MAC {request.mac_address}')
                            _set_cached_cm_index(request.cmts_ip, request.mac_address, cm_index)
                            # Now that we have cm_index, pre-fetch SG ID for fiber node
                            try:
                                fiber_node_sg_task_id = await agent_manager.send_task(
                                    cmts_agent_id, "snmp_get",
                                    {
                                        "target_ip": request.cmts_ip,
                                        "oid": f'1.3.6.1.4.1.4491.2.1.20.1.3.1.8.{cm_index}',
                                        "community": request.cmts_community or "public",
                                    },
                                    timeout=5.0,
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        self.logger.debug(f'cm_index resolution failed: {e}')

                if cmts_rxmer_result and parsed.get('success'):
                    try:
                        rxmer_result = cmts_rxmer_result
                        if rxmer_result and rxmer_result.get('result', {}).get('success'):
                            rxmer_entries = rxmer_result.get('result', {}).get('results', [])
                            base_oid = '1.3.6.1.4.1.4491.2.1.28.1.4.1.2'
                            cm_rxmer_list = []
                            for entry in rxmer_entries:
                                oid = entry.get('oid', '')
                                suffix = oid.replace(base_oid + '.', '').lstrip('.')
                                parts = suffix.split('.')
                                if len(parts) == 2:
                                    try:
                                        entry_cm_index = int(parts[0])
                                        ofdma_ifindex = int(parts[1])
                                        if cm_index is None or entry_cm_index == cm_index:
                                            val = entry.get('value')
                                            if val is not None and int(val) > 0:
                                                cm_rxmer_list.append((ofdma_ifindex, round(int(val) / 100, 2)))
                                    except (ValueError, TypeError):
                                        pass
                            cm_rxmer_list.sort(key=lambda x: x[0])
                            ofdma_channels = sorted(
                                parsed.get('upstream', {}).get('ofdma', {}).get('channels', []),
                                key=lambda c: c.get('index', 0)
                            )
                            for i, ch in enumerate(ofdma_channels):
                                if i < len(cm_rxmer_list):
                                    ch['rx_mer'] = cm_rxmer_list[i][1]
                            if cm_rxmer_list:
                                self.logger.info(f'Injected CMTS MeanRxMer for {len(cm_rxmer_list)} OFDMA channels (positional)')
                    except Exception as rxmer_err:
                        self.logger.warning(f'CMTS MeanRxMer collection failed: {rxmer_err}')

                # Collect CMTS OFDMA profile stats (IUC codewords) and inject active_iucs
                if cmts_profile_result and parsed.get('success'):
                    try:
                        prof_result = cmts_profile_result
                        if prof_result and prof_result.get('result', {}).get('success'):
                            prof_entries = prof_result.get('result', {}).get('results', [])
                            base_oid = '1.3.6.1.4.1.4491.2.1.28.1.5.1.1'
                            # Build: ofdma_ifindex -> {iuc_id -> codewords}
                            ifindex_iuc_map = {}
                            for entry in prof_entries:
                                oid = entry.get('oid', '')
                                suffix = oid.replace(base_oid + '.', '').lstrip('.')
                                parts = suffix.split('.')
                                # OID suffix: cm_index.ofdma_ifindex.iuc_id
                                if len(parts) == 3:
                                    try:
                                        entry_cm_index = int(parts[0])
                                        ofdma_ifindex = int(parts[1])
                                        iuc_id = int(parts[2])
                                        if cm_index is None or entry_cm_index == cm_index:
                                            val = int(entry.get('value') or 0)
                                            if ofdma_ifindex not in ifindex_iuc_map:
                                                ifindex_iuc_map[ofdma_ifindex] = {}
                                            ifindex_iuc_map[ofdma_ifindex][iuc_id] = val
                                    except (ValueError, TypeError):
                                        pass

                            # Match positionally (sorted ifindex order = sorted channel index order)
                            sorted_ifindices = sorted(ifindex_iuc_map.keys())
                            ofdma_channels = sorted(
                                parsed.get('upstream', {}).get('ofdma', {}).get('channels', []),
                                key=lambda c: c.get('index', 0)
                            )
                            for i, ch in enumerate(ofdma_channels):
                                if i < len(sorted_ifindices):
                                    iuc_data = ifindex_iuc_map[sorted_ifindices[i]]
                                    iuc_stats = [
                                        {'iuc': iuc_id, 'codewords': cw}
                                        for iuc_id, cw in sorted(iuc_data.items())
                                        if cw > 0
                                    ]
                                    if iuc_stats:
                                        ch['iuc_stats'] = iuc_stats
                                        ch['active_iucs'] = [s['iuc'] for s in iuc_stats]
                                        ch['current_iuc'] = iuc_stats[-1]['iuc']  # highest active IUC
                            self.logger.info(f'Injected CMTS IUC stats for {len(sorted_ifindices)} OFDMA channels')
                    except Exception as prof_err:
                        self.logger.warning(f'CMTS profile stats collection failed: {prof_err}')
                    except Exception as rxmer_err:
                        self.logger.warning(f'CMTS MeanRxMer collection failed: {rxmer_err}')

                # Resolve fiber node
                fiber_node = None
                if request.cmts_ip and request.mac_address and cmts_agent_id:
                    try:
                        fn_cm_index = _get_cached_cm_index(request.cmts_ip, request.mac_address)
                        if fiber_node_sg_task_id and fn_cm_index is not None:
                            # Fast path: use pre-fetched SG ID (sent before modem walk)
                            sg_result = await agent_manager.wait_for_task_async(fiber_node_sg_task_id, timeout=5.0)
                            cm_sg_id = None
                            if sg_result and sg_result.get('result', {}).get('success'):
                                cm_sg_id = sg_result.get('result', {}).get('value')
                            if cm_sg_id:
                                fn_task_id = await agent_manager.send_task(
                                    cmts_agent_id, "snmp_walk",
                                    {"target_ip": request.cmts_ip, "oid": '1.3.6.1.4.1.4491.2.1.20.1.12.1.3', "community": request.cmts_community or "public"},
                                    timeout=10.0,
                                )
                                fn_result = await agent_manager.wait_for_task_async(fn_task_id, timeout=10.0)
                                if fn_result and fn_result.get('result', {}).get('success'):
                                    fn_entries = fn_result.get('result', {}).get('results', [])
                                    self.logger.info(
                                        f"FN table walk: {len(fn_entries)} rows for SG ID {cm_sg_id} "
                                        f"on CMTS {request.cmts_ip}"
                                    )
                                    for entry in fn_entries:
                                        if entry.get('oid', '').endswith(f'.{cm_sg_id}'):
                                            parts = entry.get('oid', '').split('.')
                                            for i in range(len(parts) - 1, 1, -1):
                                                try:
                                                    length = int(parts[i])
                                                    if 1 <= length <= 50:
                                                        byte_parts = parts[i+1:i+1+length]
                                                        if len(byte_parts) == length:
                                                            vals = [int(p) for p in byte_parts]
                                                            # Accept printable ASCII + extended Latin-1
                                                            # (reject NUL/DEL only — allows EU operator names)
                                                            if not any(v == 0 or v == 127 for v in vals):
                                                                fiber_node = ''.join(chr(v) for v in vals)
                                                                break
                                                except (ValueError, IndexError):
                                                    continue
                                            if fiber_node:
                                                break
                                    if not fiber_node:
                                        self.logger.warning(
                                            f"FN name not found for SG ID {cm_sg_id} "
                                            f"on {request.cmts_ip} ({len(fn_entries)} rows walked)"
                                        )
                        else:
                            # If cm-index discovery just timed out, avoid repeating the
                            # same heavy CM status walk in fallback path.
                            if cmts_cmindex_timed_out:
                                self.logger.info(
                                    "Skipping fiber-node fallback CM status walk because "
                                    "cm-index task timed out in this request"
                                )
                            else:
                                # First call: full sequential lookup (also caches cm_index)
                                fiber_node = await self._get_fiber_node_from_cmts(
                                    agent_manager, cmts_agent_id, request.cmts_ip,
                                    request.mac_address, request.cmts_community or "public",
                                    walk_timeout=cmts_task_timeout,
                                )
                    except Exception as fn_err:
                        self.logger.debug(f'Fiber node lookup failed: {fn_err}')

                # Build ofdm_stats from new CMTS walks (always run when CM walk succeeded,
                # so DS profile codewords from modem show even if CMTS tasks timed out)
                ofdm_stats = None
                if parsed.get('success'):
                    from .parser import parse_ofdm_stats_raw
                    ofdm_stats = parse_ofdm_stats_raw(
                        cm_index=cm_index,
                        partial_reason_result=cmts_partial_reason_result,
                        us_iuc_stats_result=cmts_us_iuc_stats_result,
                        ds_ofdm_speed_result=cmts_ds_ofdm_speed_result,
                        ds_subcarrier_result=cmts_ds_subcarrier_result,
                        ifname_result=cmts_ifname_result,
                        cmts_profile_result=cmts_profile_result,
                        # CM-side DS profile stats already in parsed
                        cm_ds_ofdm_channels=parsed.get('downstream', {}).get('ofdm', {}).get('channels', []),
                        cm_us_ofdma_channels=parsed.get('upstream', {}).get('ofdma', {}).get('channels', []),
                    )

                if parsed.get("success"):
                    timing = parsed.get("timing", {})
                    if walk_durations:
                        timing["walk_durations"] = walk_durations
                    return ChannelStatsResponse(
                        success=True,
                        status=0,
                        mac_address=parsed.get("mac_address"),
                        modem_ip=parsed.get("modem_ip"),
                        fiber_node=fiber_node,
                        timestamp=parsed.get("timestamp"),
                        timing=timing,
                        downstream=parsed.get("downstream"),
                        upstream=parsed.get("upstream"),
                        ofdm_stats=ofdm_stats,
                    )
                else:
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error=parsed.get("error") or "Parsing failed"
                    )

            except ValueError as e:
                self.logger.error(f"Agent error: {e}")
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                self.logger.error(f"Channel stats failed: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get channel stats: {str(e)}")
    
    async def _get_fiber_node_from_cmts(
        self, agent_manager, agent_id: str, cmts_ip: str, 
        mac_address: str, community: str, walk_timeout: float = 30.0
    ) -> str:
        """Lookup fiber node from CMTS using agent SNMP commands."""
        try:
            self.logger.info(f"Looking up fiber node for {mac_address} on CMTS {cmts_ip}")
            
            # Normalize MAC address to match CMTS format (shortened, colons)
            # CMTS stores MACs like 44:5:3f:d4:19:15 (no leading zeros in bytes)
            mac_clean = mac_address.replace(':', '').replace('-', '').replace('.', '').lower()
            self.logger.info(f"Normalized MAC: {mac_address} -> {mac_clean}")
            
            # Walk docsIf3CmtsCmRegStatusMacAddr to find CM index
            oid = '1.3.6.1.4.1.4491.2.1.20.1.3.1.2'  # docsIf3CmtsCmRegStatusMacAddr
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=walk_timeout)
            result = await agent_manager.wait_for_task_async(task_id, timeout=walk_timeout)
            
            if not result or not result.get("result", {}).get("success"):
                self.logger.warning(f"Failed to walk CM MAC table on CMTS {cmts_ip}")
                return None
            
            # Find CM index by matching MAC address (values may be hex like 0x5cfa25a1ca92)
            cm_index = None
            results = result.get("result", {}).get("results", [])
            for entry in results:
                val = entry.get("value", "")
                if isinstance(val, str):
                    entry_mac = val.replace('0x', '').replace(' ', '').replace(':', '').replace('-', '').lower()
                    if entry_mac == mac_clean:
                        oid_str = entry.get("oid", "")
                        suffix = oid_str.split('1.3.6.1.4.1.4491.2.1.20.1.3.1.2.')[-1]
                        try:
                            cm_index = suffix.strip('.')
                        except (ValueError, IndexError):
                            pass
                        break
            
            if not cm_index:
                self.logger.warning(f"MAC {mac_address} not found in CMTS table")
                return None

            # Cache cm_index for future calls (avoids MAC table walk)
            _set_cached_cm_index(cmts_ip, mac_address, int(cm_index))
            
            # Get CM's Service Group ID via snmpget (direct, no walk needed)
            task_id = await agent_manager.send_task(agent_id, "snmp_get", {"target_ip": cmts_ip, "oid": f'1.3.6.1.4.1.4491.2.1.20.1.3.1.8.{cm_index}', "community": community}, timeout=5.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=5.0)
            
            cm_sg_id = None
            if result and result.get("result", {}).get("success"):
                cm_sg_id = result.get("result", {}).get("value")
            
            if not cm_sg_id:
                self.logger.warning(f"No Service Group ID found for CM index {cm_index}")
                return None
            
            # Walk the full fiber node table and match by SG ID directly
            # Uses shared fiber_node_utils for OID parsing (unified with rxmer/router.py)
            self.logger.info(f"Walking full fiber node table to find SG ID {cm_sg_id}: {OID_MD_NODE_STATUS_MD_DS_SG_ID}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": OID_MD_NODE_STATUS_MD_DS_SG_ID, "community": community}, timeout=10.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=10.0)
            
            if result and result.get("result", {}).get("success"):
                results = result.get("result", {}).get("results", [])
                self.logger.info(f"Fiber node table has {len(results)} entries, searching for SG ID {cm_sg_id}")
                
                # Find fiber node by matching SG ID using shared utility
                for entry in results:
                    oid_str = entry.get("oid", "")
                    fn_name = parse_fn_name_from_oid_by_sg_id(
                        oid_str, OID_MD_NODE_STATUS_MD_DS_SG_ID, int(cm_sg_id)
                    )
                    if fn_name:
                        self.logger.info(f"Found fiber node for {mac_address}: {fn_name} (SG ID: {cm_sg_id})")
                        return fn_name
                
                self.logger.warning(f"No fiber node found matching SG ID {cm_sg_id}")
            else:
                self.logger.warning(f"Fiber node table walk failed")
            return None
        except Exception as e:
            self.logger.warning(f"Failed to get fiber node: {e}")
            return None


# Router instance for auto-discovery
router = ChannelStatsRouter().router
