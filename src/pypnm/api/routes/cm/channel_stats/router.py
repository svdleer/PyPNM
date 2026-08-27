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


def _parse_octet_string_to_bytes(value: object) -> bytes:
    """Convert common SNMP octet-string representations to raw bytes."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, (list, tuple)):
        try:
            return bytes(int(part) for part in value)
        except (TypeError, ValueError):
            return b""

    text = str(value).strip()
    if not text:
        return b""
    if " = " in text:
        text = text.split(" = ", 1)[1].strip()
    if text.lower().startswith("hex-string:"):
        text = text.split(":", 1)[1].strip()
    if text.lower().startswith("0x"):
        text = text[2:]

    compact = text.replace(" ", "").replace(":", "").replace("-", "")
    if compact and len(compact) % 2 == 0:
        try:
            return bytes.fromhex(compact)
        except ValueError:
            return b""
    return b""


def _parse_us_profile_iuc_map(result: dict | None, cm_index: int | None) -> dict[int, list[int]]:
    """Parse docsIf31CmtsCmRegStatusUsProfileIucList into {ifindex: [iuc, ...]}."""
    if not result or cm_index is None:
        return {}

    payload = result.get("result", {}) if isinstance(result, dict) else {}
    entries = payload.get("results") or []
    if not entries and payload.get("output"):
        entries = [{
            "oid": f"1.3.6.1.4.1.4491.2.1.28.1.3.1.3.{cm_index}",
            "value": payload.get("output"),
        }]

    parsed: dict[int, list[int]] = {}
    prefix = "1.3.6.1.4.1.4491.2.1.28.1.3.1.3."
    for entry in entries:
        oid = str(entry.get("oid", ""))
        if not oid.startswith(prefix):
            continue
        try:
            entry_cm_index = int(oid[len(prefix):].split(".")[0])
        except (TypeError, ValueError):
            continue
        if entry_cm_index != cm_index:
            continue

        raw_bytes = _parse_octet_string_to_bytes(entry.get("value"))
        pos = 0
        while pos + 5 < len(raw_bytes):
            ifindex = int.from_bytes(raw_bytes[pos:pos + 4], byteorder="big", signed=False)
            count = raw_bytes[pos + 4]
            pos += 5
            if count <= 0 or pos + count > len(raw_bytes):
                break
            iucs = [int(raw_bytes[pos + offset]) for offset in range(count)]
            pos += count
            if ifindex and iucs:
                parsed[ifindex] = iucs
    return parsed


def _parse_ds_profile_id_map(result: dict | None, cm_index: int | None) -> dict[int, list[int]]:
    """Parse docsIf31CmtsCmRegStatusDsProfileIdList into {ifindex: [profile_id, ...]}."""
    if not result or cm_index is None:
        return {}

    payload = result.get("result", {}) if isinstance(result, dict) else {}
    entries = payload.get("results") or []
    if not entries and payload.get("output"):
        entries = [{
            "oid": f"1.3.6.1.4.1.4491.2.1.28.1.3.1.2.{cm_index}",
            "value": payload.get("output"),
        }]

    parsed: dict[int, list[int]] = {}
    prefix = "1.3.6.1.4.1.4491.2.1.28.1.3.1.2."
    for entry in entries:
        oid = str(entry.get("oid", ""))
        if not oid.startswith(prefix):
            continue
        try:
            entry_cm_index = int(oid[len(prefix):].split(".")[0])
        except (TypeError, ValueError):
            continue
        if entry_cm_index != cm_index:
            continue

        raw_bytes = _parse_octet_string_to_bytes(entry.get("value"))
        pos = 0
        while pos + 5 < len(raw_bytes):
            ifindex = int.from_bytes(raw_bytes[pos:pos + 4], byteorder="big", signed=False)
            count = raw_bytes[pos + 4]
            pos += 5
            if count <= 0 or pos + count > len(raw_bytes):
                break
            profile_ids = [int(raw_bytes[pos + offset]) for offset in range(count)]
            pos += count
            valid_ids = [p for p in profile_ids if 0 <= p <= 15]
            if ifindex and valid_ids:
                parsed[ifindex] = valid_ids
    return parsed


def _agent_snmp_context(target_role: str, community: str | None) -> dict[str, str]:
    context = {"target_role": target_role}
    if community:
        context["community"] = community
    return context


class ChannelStatsRequest(BaseModel):
    """Request model for channel stats."""
    mac_address: str = Field(..., description="Cable modem MAC address")
    modem_ip: str = Field(..., description="Cable modem IP address")
    community: Optional[str] = Field(default=None, description="SNMP community string")
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
                        {"target_ip": request.modem_ip, "oid": "1.3.6.1.2.1.1.1.0", **_agent_snmp_context("cm", request.community)},
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
                        **_agent_snmp_context("cm", request.community),
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
                cmts_snr_task_id = None
                cmts_sysdescr_task_id = None
                cmts_cmindex_task_id = None
                cmts_chanid_task_id = None
                cmts_profile_task_id = None
                fiber_node_sg_task_id = None
                cmts_partial_reason_task_id = None
                cmts_us_iuc_stats_task_id = None
                cmts_us_profile_iuc_list_task_id = None
                cmts_ds_profile_id_list_task_id = None
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
                                    **_agent_snmp_context("cmts", request.cmts_community),
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
                                    **_agent_snmp_context("cmts", request.cmts_community),
                                },
                                timeout=cmts_task_timeout,
                            )
                        except Exception as e:
                            self.logger.debug(f"cm_index pre-task failed: {e}")

                if request.cmts_ip and request.cmts_stats and cmts_agent_id:
                    try:
                        cmts_sysdescr_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_get",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.2.1.1.1.0',
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=5.0,
                        )
                        if cached_cm_index is None:
                            cmts_ofdma_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": '1.3.6.1.4.1.4491.2.1.28.1.4',
                                    **_agent_snmp_context("cmts", request.cmts_community),
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
                                    **_agent_snmp_context("cmts", request.cmts_community),
                                },
                                timeout=cmts_task_timeout,
                            )
                            # Fallback SNR source (docsIf3CmtsCmUsStatusSignalNoise)
                            # used when docsIf31CmtsCmMeanRxMer returns 0 (Casa/EVO)
                            cmts_snr_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.20.1.4.1.4.{cached_cm_index}',
                                    **_agent_snmp_context("cmts", request.cmts_community),
                                },
                                timeout=cmts_task_timeout,
                            )
                            cmts_profile_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_walk",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.28.1.5.1.1.{cached_cm_index}',
                                    **_agent_snmp_context("cmts", request.cmts_community),
                                },
                                timeout=cmts_task_timeout,
                            )
                            cmts_us_profile_iuc_list_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_get",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.28.1.3.1.3.{cached_cm_index}',
                                    **_agent_snmp_context("cmts", request.cmts_community),
                                },
                                timeout=cmts_task_timeout,
                            )
                            cmts_ds_profile_id_list_task_id = await agent_manager.send_task(
                                cmts_agent_id, "snmp_get",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f'1.3.6.1.4.1.4491.2.1.28.1.3.1.2.{cached_cm_index}',
                                    **_agent_snmp_context("cmts", request.cmts_community),
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
                                    **_agent_snmp_context("cmts", request.cmts_community),
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
                                    **_agent_snmp_context("cmts", request.cmts_community),
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
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=cmts_task_timeout,
                        )
                        # New: US OFDMA IUC stats (per-channel aggregate, small table)
                        cmts_us_iuc_stats_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.24',
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=cmts_task_timeout,
                        )
                        # New: DS OFDM profile speed per channel+profile
                        cmts_ds_ofdm_speed_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.20',
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=cmts_task_timeout,
                        )
                        # New: DS OFDM subcarrier status (modulation per range)
                        cmts_ds_subcarrier_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.21',
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=cmts_task_timeout,
                        )
                        # ifName table — maps ifIndex → interface name (e.g. Cable8/0/0)
                        cmts_ifname_task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.2.1.31.1.1.1.1',
                                **_agent_snmp_context("cmts", request.cmts_community),
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
                    cmts_sysdescr_result,
                    cmts_cmindex_result,
                    cmts_rxmer_result,
                    cmts_snr_result,
                    cmts_profile_result,
                    cmts_partial_reason_result,
                    cmts_us_iuc_stats_result,
                    cmts_us_profile_iuc_list_result,
                    cmts_ds_profile_id_list_result,
                    cmts_ds_ofdm_speed_result,
                    cmts_ds_subcarrier_result,
                    cmts_ifname_result,
                ) = await asyncio.gather(
                    _safe_wait_task(cmts_ofdma_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_sysdescr_task_id, 5.0),
                    _safe_wait_task(cmts_cmindex_task_id, max(cmts_task_timeout, 45.0)),  # MAC table is large (~9k entries, ~33s)
                    _safe_wait_task(cmts_rxmer_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_snr_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_profile_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_partial_reason_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_us_iuc_stats_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_us_profile_iuc_list_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ds_profile_id_list_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ds_ofdm_speed_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ds_subcarrier_task_id, cmts_task_timeout),
                    _safe_wait_task(cmts_ifname_task_id, cmts_task_timeout),
                )

                cmts_cmindex_timed_out = bool(
                    cmts_cmindex_task_id
                    and isinstance(cmts_cmindex_result, dict)
                    and 'timeout' in str(cmts_cmindex_result.get('error', '')).lower()
                )

                # No fallback injection here. If authoritative data is missing,
                # we rely on one explicit retry of registration list reads later.

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
                                        **_agent_snmp_context("cmts", request.cmts_community),
                                    },
                                    timeout=5.0,
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        self.logger.debug(f'cm_index resolution failed: {e}')

                # When cm_index was resolved late (not cached), fetch per-modem
                # UsProfileIucList now so current_iuc can be derived reliably.
                if (
                    cm_index is not None
                    and request.cmts_ip
                    and cmts_agent_id
                    and cmts_us_profile_iuc_list_result is None
                ):
                    try:
                        _task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_get",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": f'1.3.6.1.4.1.4491.2.1.28.1.3.1.3.{cm_index}',
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=cmts_task_timeout,
                        )
                        cmts_us_profile_iuc_list_result = await _safe_wait_task(_task_id, cmts_task_timeout)
                    except Exception as _iuc_list_err:
                        self.logger.debug(f'UsProfileIucList late fetch failed: {_iuc_list_err}')

                if (
                    cm_index is not None
                    and request.cmts_ip
                    and cmts_agent_id
                    and cmts_ds_profile_id_list_result is None
                ):
                    try:
                        _task_id = await agent_manager.send_task(
                            cmts_agent_id, "snmp_get",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": f'1.3.6.1.4.1.4491.2.1.28.1.3.1.2.{cm_index}',
                                **_agent_snmp_context("cmts", request.cmts_community),
                            },
                            timeout=cmts_task_timeout,
                        )
                        cmts_ds_profile_id_list_result = await _safe_wait_task(_task_id, cmts_task_timeout)
                    except Exception as _ds_profile_list_err:
                        self.logger.debug(f'DsProfileIdList late fetch failed: {_ds_profile_list_err}')

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
                                            if val is not None:
                                                cm_rxmer_list.append((ofdma_ifindex, round(int(val) / 100, 2)))
                                    except (ValueError, TypeError):
                                        pass
                            cm_rxmer_list.sort(key=lambda x: x[0])
                            ofdma_channels = sorted(
                                parsed.get('upstream', {}).get('ofdma', {}).get('channels', []),
                                key=lambda c: c.get('index', 0)
                            )
                            injected_rxmer = 0
                            for i, ch in enumerate(ofdma_channels):
                                if i < len(cm_rxmer_list):
                                    sample = cm_rxmer_list[i][1]
                                    if sample is not None and sample > 0:
                                        ch['rx_mer'] = sample
                                        injected_rxmer += 1
                            if cm_rxmer_list:
                                self.logger.info(f'Injected CMTS MeanRxMer for {injected_rxmer} OFDMA channels (positional, zero-suppressed)')

                            # No vendor fallback injection for RxMER.
                    except Exception as rxmer_err:
                        self.logger.warning(f'CMTS MeanRxMer collection failed: {rxmer_err}')

                # Collect CMTS OFDMA profile stats (IUC codewords) for diagnostics only.
                # Active/current IUC business logic is sourced exclusively from
                # docsIf31CmtsCmRegStatusUsProfileIucList.
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
                                    ]
                                    if iuc_stats:
                                        ch['iuc_stats'] = iuc_stats
                            # Mirror codeword stats into OFDM stats US rows.
                            for row in parsed.get('ofdm_stats', {}).get('us_iuc_stats', []) or []:
                                try:
                                    row_ifindex = int(row.get('ifindex'))
                                except (TypeError, ValueError):
                                    continue
                                iuc_data = ifindex_iuc_map.get(row_ifindex, {})
                                if iuc_data:
                                    row['iuc_codewords'] = [
                                        {'iuc': iuc_id, 'codewords': cw}
                                        for iuc_id, cw in sorted(iuc_data.items())
                                    ]
                            self.logger.info(f'Injected CMTS IUC stats for {len(sorted_ifindices)} OFDMA channels')
                    except Exception as prof_err:
                        self.logger.warning(f'CMTS profile stats collection failed: {prof_err}')
                    except Exception as rxmer_err:
                        self.logger.warning(f'CMTS MeanRxMer collection failed: {rxmer_err}')

                us_profile_iuc_map: dict[int, list[int]] = {}
                ds_profile_id_map: dict[int, list[int]] = {}

                async def _fetch_channel_id_map(base_col_oid: str, ifindices: list[int]) -> dict[int, int]:
                    """Resolve CMTS channelId by ifIndex via explicit SNMP GETs."""
                    out: dict[int, int] = {}
                    if not ifindices or not request.cmts_ip or not cmts_agent_id:
                        return out
                    task_pairs: list[tuple[int, str]] = []
                    for ifidx in sorted(set(ifindices)):
                        try:
                            task_id = await agent_manager.send_task(
                                cmts_agent_id,
                                "snmp_get",
                                {
                                    "target_ip": request.cmts_ip,
                                    "oid": f"{base_col_oid}.{ifidx}",
                                    **_agent_snmp_context("cmts", request.cmts_community),
                                },
                                timeout=cmts_task_timeout,
                            )
                            task_pairs.append((ifidx, task_id))
                        except Exception:
                            continue
                    for ifidx, task_id in task_pairs:
                        resp = await _safe_wait_task(task_id, cmts_task_timeout)
                        payload = resp.get('result', resp) if isinstance(resp, dict) else {}
                        if not isinstance(payload, dict) or not payload.get('success'):
                            continue
                        value = payload.get('value') or payload.get('output')
                        if value is None and isinstance(payload.get('results'), list) and payload.get('results'):
                            value = (payload.get('results')[0] or {}).get('value')
                        try:
                            out[ifidx] = int(value)
                        except (TypeError, ValueError):
                            continue
                    return out

                # Prefer per-modem UsProfileIucList for active/current IUC mapping.
                # This remains valid even when per-IUC codeword counters are all zero.
                if parsed.get('success'):
                    try:
                        us_profile_iuc_map = _parse_us_profile_iuc_map(cmts_us_profile_iuc_list_result, cm_index)
                        if not us_profile_iuc_map and cm_index is not None and request.cmts_ip and cmts_agent_id:
                            try:
                                retry_task_id = await agent_manager.send_task(
                                    cmts_agent_id,
                                    "snmp_get",
                                    {
                                        "target_ip": request.cmts_ip,
                                        "oid": f'1.3.6.1.4.1.4491.2.1.28.1.3.1.3.{cm_index}',
                                        **_agent_snmp_context("cmts", request.cmts_community),
                                    },
                                    timeout=cmts_task_timeout,
                                )
                                retry_result = await _safe_wait_task(retry_task_id, cmts_task_timeout)
                                us_profile_iuc_map = _parse_us_profile_iuc_map(retry_result, cm_index)
                                if us_profile_iuc_map:
                                    self.logger.info('UsProfileIucList retry succeeded for cm_index=%s', cm_index)
                            except Exception as retry_err:
                                self.logger.debug(f'UsProfileIucList retry failed: {retry_err}')
                        if us_profile_iuc_map:
                            injected_exact = 0
                            injected_signature = 0
                            injected_second_pass = 0

                            ofdma_channels = parsed.get('upstream', {}).get('ofdma', {}).get('channels', [])
                            # Exact ifIndex match first.
                            for ch in ofdma_channels:
                                try:
                                    ch_ifindex = int(ch.get('index'))
                                except (TypeError, ValueError):
                                    continue
                                active_iucs = sorted(set(us_profile_iuc_map.get(ch_ifindex, [])))
                                if not active_iucs:
                                    continue
                                ch['active_iucs'] = active_iucs
                                ch['current_iuc'] = max(active_iucs)
                                injected_exact += 1

                            # Deterministic identity match by active-IUC signature.
                            if injected_exact == 0 and ofdma_channels:
                                sig_to_ifidx: dict[tuple[int, ...], int] = {}
                                ambiguous_sigs: set[tuple[int, ...]] = set()
                                for ifidx, iucs in us_profile_iuc_map.items():
                                    sig = tuple(sorted(set(iucs)))
                                    if not sig:
                                        continue
                                    if sig in sig_to_ifidx and sig_to_ifidx[sig] != ifidx:
                                        ambiguous_sigs.add(sig)
                                    else:
                                        sig_to_ifidx[sig] = ifidx
                                for ch in ofdma_channels:
                                    codeword_rows = ch.get('iuc_stats') or []
                                    nonzero_iucs = sorted(
                                        {
                                            int(r.get('iuc'))
                                            for r in codeword_rows
                                            if int(r.get('codewords') or 0) > 0
                                        }
                                    )
                                    if not nonzero_iucs:
                                        continue
                                    sig = tuple(nonzero_iucs)
                                    if sig in ambiguous_sigs:
                                        continue
                                    ifidx = sig_to_ifidx.get(sig)
                                    if not ifidx:
                                        continue
                                    active_iucs = sorted(set(us_profile_iuc_map.get(ifidx, [])))
                                    if not active_iucs:
                                        continue
                                    ch['active_iucs'] = active_iucs
                                    ch['current_iuc'] = max(active_iucs)
                                    injected_signature += 1

                            # Deterministic second pass: explicit channelId lookup by CMTS ifIndex.
                            if (injected_exact + injected_signature) == 0 and ofdma_channels:
                                cmts_chid_by_ifindex = await _fetch_channel_id_map(
                                    '1.3.6.1.4.1.4491.2.1.28.1.13.1.12',
                                    list(us_profile_iuc_map.keys()),
                                )
                                if cmts_chid_by_ifindex:
                                    ifindex_by_chid: dict[int, int] = {}
                                    for ifidx, chid in cmts_chid_by_ifindex.items():
                                        # Keep only unique channel_id mappings.
                                        if chid in ifindex_by_chid and ifindex_by_chid[chid] != ifidx:
                                            ifindex_by_chid[chid] = -1
                                        else:
                                            ifindex_by_chid[chid] = ifidx

                                    for ch in ofdma_channels:
                                        try:
                                            chid = int(ch.get('channel_id'))
                                        except (TypeError, ValueError):
                                            continue
                                        ifidx = ifindex_by_chid.get(chid)
                                        if ifidx is None or ifidx <= 0:
                                            continue
                                        active_iucs = sorted(set(us_profile_iuc_map.get(ifidx, [])))
                                        if not active_iucs:
                                            continue
                                        ch['active_iucs'] = active_iucs
                                        ch['current_iuc'] = max(active_iucs)
                                        injected_second_pass += 1

                            total_injected = injected_exact + injected_signature + injected_second_pass
                            if total_injected:
                                self.logger.info(
                                    'Injected per-modem UsProfileIucList for %s OFDMA channels '
                                    '(exact=%s, signature=%s, second_pass=%s)',
                                    total_injected,
                                    injected_exact,
                                    injected_signature,
                                    injected_second_pass,
                                )
                    except Exception as iuc_map_err:
                        self.logger.warning(f'UsProfileIucList injection failed: {iuc_map_err}')

                # Prefer per-modem DsProfileIdList for active/current DS profile mapping.
                if parsed.get('success'):
                    try:
                        ds_profile_id_map = _parse_ds_profile_id_map(cmts_ds_profile_id_list_result, cm_index)
                        if not ds_profile_id_map and cm_index is not None and request.cmts_ip and cmts_agent_id:
                            try:
                                retry_task_id = await agent_manager.send_task(
                                    cmts_agent_id,
                                    "snmp_get",
                                    {
                                        "target_ip": request.cmts_ip,
                                        "oid": f'1.3.6.1.4.1.4491.2.1.28.1.3.1.2.{cm_index}',
                                        **_agent_snmp_context("cmts", request.cmts_community),
                                    },
                                    timeout=cmts_task_timeout,
                                )
                                retry_result = await _safe_wait_task(retry_task_id, cmts_task_timeout)
                                ds_profile_id_map = _parse_ds_profile_id_map(retry_result, cm_index)
                                if ds_profile_id_map:
                                    self.logger.info('DsProfileIdList retry succeeded for cm_index=%s', cm_index)
                            except Exception as retry_err:
                                self.logger.debug(f'DsProfileIdList retry failed: {retry_err}')
                        if ds_profile_id_map:
                            injected_exact = 0
                            injected_signature = 0
                            injected_second_pass = 0
                            ds_channels = parsed.get('downstream', {}).get('ofdm', {}).get('channels', [])

                            for ch in ds_channels:
                                try:
                                    ch_ifindex = int(ch.get('index'))
                                except (TypeError, ValueError):
                                    continue
                                profiles = sorted(set(ds_profile_id_map.get(ch_ifindex, [])))
                                if not profiles:
                                    continue
                                ch['profiles'] = profiles
                                non_zero = [p for p in profiles if p > 0]
                                ch['current_profile'] = max(non_zero) if non_zero else max(profiles)
                                injected_exact += 1

                            # Deterministic identity match by assigned-profile signature.
                            if injected_exact == 0 and ds_channels:
                                sig_to_ifidx: dict[tuple[int, ...], int] = {}
                                ambiguous_sigs: set[tuple[int, ...]] = set()
                                for ifidx, pids in ds_profile_id_map.items():
                                    sig = tuple(sorted(set(pids)))
                                    if not sig:
                                        continue
                                    if sig in sig_to_ifidx and sig_to_ifidx[sig] != ifidx:
                                        ambiguous_sigs.add(sig)
                                    else:
                                        sig_to_ifidx[sig] = ifidx
                                for ch in ds_channels:
                                    sig = tuple(sorted(set(int(p) for p in (ch.get('profiles') or []))))
                                    if not sig or sig in ambiguous_sigs:
                                        continue
                                    ifidx = sig_to_ifidx.get(sig)
                                    if not ifidx:
                                        continue
                                    profiles = sorted(set(ds_profile_id_map.get(ifidx, [])))
                                    if not profiles:
                                        continue
                                    ch['profiles'] = profiles
                                    non_zero = [p for p in profiles if p > 0]
                                    ch['current_profile'] = max(non_zero) if non_zero else max(profiles)
                                    injected_signature += 1

                            # Deterministic second pass: explicit channelId lookup by CMTS ifIndex.
                            if (injected_exact + injected_signature) == 0 and ds_channels:
                                cmts_chid_by_ifindex = await _fetch_channel_id_map(
                                    '1.3.6.1.4.1.4491.2.1.28.1.9.1.1',
                                    list(ds_profile_id_map.keys()),
                                )
                                if cmts_chid_by_ifindex:
                                    ifindex_by_chid: dict[int, int] = {}
                                    for ifidx, chid in cmts_chid_by_ifindex.items():
                                        if chid in ifindex_by_chid and ifindex_by_chid[chid] != ifidx:
                                            ifindex_by_chid[chid] = -1
                                        else:
                                            ifindex_by_chid[chid] = ifidx

                                    for ch in ds_channels:
                                        try:
                                            chid = int(ch.get('channel_id'))
                                        except (TypeError, ValueError):
                                            continue
                                        ifidx = ifindex_by_chid.get(chid)
                                        if ifidx is None or ifidx <= 0:
                                            continue
                                        profiles = sorted(set(ds_profile_id_map.get(ifidx, [])))
                                        if not profiles:
                                            continue
                                        ch['profiles'] = profiles
                                        non_zero = [p for p in profiles if p > 0]
                                        ch['current_profile'] = max(non_zero) if non_zero else max(profiles)
                                        injected_second_pass += 1

                            total_injected = injected_exact + injected_signature + injected_second_pass

                            if total_injected:
                                self.logger.info(
                                    'Injected per-modem DsProfileIdList for %s OFDM channels '
                                    '(exact=%s, signature=%s, second_pass=%s)',
                                    total_injected,
                                    injected_exact,
                                    injected_signature,
                                    injected_second_pass,
                                )
                    except Exception as ds_profile_err:
                        self.logger.warning(f'DsProfileIdList injection failed: {ds_profile_err}')

                # Log-only observability: when authoritative registration lists
                # are unavailable or fail to populate active/current values.
                if parsed.get('success'):
                    ds_channels = parsed.get('downstream', {}).get('ofdm', {}).get('channels', []) or []
                    us_channels = parsed.get('upstream', {}).get('ofdma', {}).get('channels', []) or []
                    missing_ds = bool(ds_channels) and not any(ch.get('current_profile') is not None for ch in ds_channels)
                    missing_us = bool(us_channels) and not any(ch.get('current_iuc') is not None for ch in us_channels)
                    if missing_ds or missing_us:
                        self.logger.warning(
                            'Authoritative profile assignment missing: cmts=%s mac=%s cm_index=%s '
                            'ds_channels=%s us_channels=%s ds_profile_rows=%s us_iuc_rows=%s',
                            request.cmts_ip,
                            request.mac_address,
                            cm_index,
                            len(ds_channels),
                            len(us_channels),
                            len(ds_profile_id_map),
                            len(us_profile_iuc_map),
                        )

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
                                    {"target_ip": request.cmts_ip, "oid": '1.3.6.1.4.1.4491.2.1.20.1.12.1.3', **_agent_snmp_context("cmts", request.cmts_community)},
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
                                    request.mac_address, request.cmts_community,
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

                    # Align stats-page rows with authoritative current markers
                    # already resolved on parsed downstream/upstream channel rows.
                    if isinstance(ofdm_stats, dict):
                        ds_channels = parsed.get('downstream', {}).get('ofdm', {}).get('channels', []) or []
                        ds_rows = ofdm_stats.get('ds_profiles', []) or []
                        if ds_channels and ds_rows:
                            current_by_channel = {}
                            for ch in ds_channels:
                                try:
                                    chid = int(ch.get('channel_id'))
                                    cur = ch.get('current_profile')
                                    if cur is not None:
                                        current_by_channel[chid] = int(cur)
                                except (TypeError, ValueError):
                                    continue
                            for row in ds_rows:
                                try:
                                    chid = int(row.get('channel_id'))
                                except (TypeError, ValueError):
                                    continue
                                if chid in current_by_channel:
                                    row['current_profile'] = current_by_channel[chid]

                        us_channels = parsed.get('upstream', {}).get('ofdma', {}).get('channels', []) or []
                        us_rows = ofdm_stats.get('us_iuc_stats', []) or []
                        if us_channels and us_rows:
                            # Authoritative direct mapping by CMTS ifindex from UsProfileIucList.
                            for row in us_rows:
                                try:
                                    row_ifindex = int(row.get('ifindex'))
                                except (TypeError, ValueError):
                                    continue
                                active_iucs = sorted(set(us_profile_iuc_map.get(row_ifindex, [])))
                                if active_iucs:
                                    row['active_iucs'] = active_iucs
                                    row['current_iuc'] = max(active_iucs)

                            # Exact namespace match (rare): row.ifindex == channel.index
                            for row in us_rows:
                                try:
                                    row_ifindex = int(row.get('ifindex'))
                                except (TypeError, ValueError):
                                    continue
                                match = next((c for c in us_channels if int(c.get('index') or -1) == row_ifindex), None)
                                if not match:
                                    continue
                                active_iucs = match.get('active_iucs')
                                current_iuc = match.get('current_iuc')
                                if active_iucs:
                                    row['active_iucs'] = active_iucs
                                if current_iuc is not None:
                                    row['current_iuc'] = current_iuc

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
        mac_address: str, community: str | None, walk_timeout: float = 30.0
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
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, **_agent_snmp_context("cmts", community)}, timeout=walk_timeout)
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
            task_id = await agent_manager.send_task(agent_id, "snmp_get", {"target_ip": cmts_ip, "oid": f'1.3.6.1.4.1.4491.2.1.20.1.3.1.8.{cm_index}', **_agent_snmp_context("cmts", community)}, timeout=5.0)
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
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": OID_MD_NODE_STATUS_MD_DS_SG_ID, **_agent_snmp_context("cmts", community)}, timeout=10.0)
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
