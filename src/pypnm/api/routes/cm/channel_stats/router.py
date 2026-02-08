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

import logging
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    skip_connectivity_check: bool = Field(default=False, description="Skip ping/SNMP check")


class ChannelStatsResponse(BaseModel):
    """Response model for channel stats."""
    success: bool
    status: int = 0
    mac_address: Optional[str] = None
    modem_ip: Optional[str] = None
    timestamp: Optional[str] = None
    timing: Optional[dict] = None
    downstream: Optional[dict] = None
    upstream: Optional[dict] = None
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
            
            # Find an available agent
            agents = agent_manager.get_available_agents()
            if not agents:
                raise HTTPException(status_code=503, detail="No agents available")
            
            agent_id = agents[0].get("agent_id")
            if not agent_id:
                raise HTTPException(status_code=503, detail="No valid agent found")
            
            self.logger.info(f"Getting channel stats for {request.modem_ip} via agent {agent_id}")
            
            try:
                # Define table OIDs - agent will walk these in parallel
                table_oids = [
                    '1.3.6.1.2.1.10.127.1.1.1',     # docsIfDownChannelTable
                    '1.3.6.1.2.1.10.127.1.1.4',     # docsIfSigQTable
                    '1.3.6.1.4.1.4491.2.1.20.1.24', # docsIf3SignalQualityExtTable
                    '1.3.6.1.4.1.4491.2.1.28.1.9',  # docsIf31CmDsOfdmChanTable
                    '1.3.6.1.4.1.4491.2.1.28.1.11', # docsIf31CmDsOfdmChannelPowerTable
                    '1.3.6.1.2.1.10.127.1.1.2',     # docsIfUpChannelTable
                    '1.3.6.1.4.1.4491.2.1.20.1.2',  # docsIf3CmStatusUsTable
                    '1.3.6.1.4.1.4491.2.1.28.1.13', # docsIf31CmUsOfdmaChanTable
                    '1.3.6.1.4.1.4491.2.1.28.1.12', # docsIf31CmStatusOfdmaUsTable
                ]
                
                # Send parallel walk task to agent
                import time
                start_time = time.time()
                
                # Do connectivity check first if not skipped
                if not request.skip_connectivity_check:
                    # Quick SNMP check
                    check_task_id = await agent_manager.send_task(
                        agent_id, "snmp_get",
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
                
                # Walk all tables in parallel (agent has snmp_parallel_walk)
                task_id = await agent_manager.send_task(
                    agent_id,
                    "snmp_parallel_walk",
                    {
                        "ip": request.modem_ip,
                        "oids": table_oids,
                        "community": request.community,
                        "timeout": 30
                    },
                    timeout=40.0
                )
                
                # Wait for result
                result = await agent_manager.wait_for_task_async(task_id, timeout=40.0)
                
                if not result:
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error="Agent task timed out"
                    )
                
                # Extract raw SNMP walk results
                agent_result = result.get("result", {})
                if not agent_result.get("success"):
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error=agent_result.get("error") or "SNMP walk failed"
                    )
                
                raw_results = agent_result.get("results", {})
                walk_time = time.time() - start_time
                
                # Parse results in API (NOT in agent)
                parsed = parse_channel_stats_raw(
                    raw_results, walk_time, request.mac_address, request.modem_ip
                )
                
                # Lookup fiber node from CMTS if provided
                import sys
                print(f"[FIBER_NODE_DEBUG] Checking fiber node lookup: cmts_ip={request.cmts_ip}, mac={request.mac_address}", file=sys.stderr, flush=True)
                fiber_node = None
                if request.cmts_ip and request.mac_address:
                    print(f"[FIBER_NODE_DEBUG] Calling fiber node lookup", file=sys.stderr, flush=True)
                    fiber_node = await self._get_fiber_node_from_cmts(
                        agent_manager, agent_id, request.cmts_ip, 
                        request.mac_address, request.cmts_community or "public"
                    )
                    print(f"[FIBER_NODE_DEBUG] Fiber node result: {fiber_node}", file=sys.stderr, flush=True)
                else:
                    self.logger.warning(f"Skipping fiber node lookup: cmts_ip={request.cmts_ip}, mac={request.mac_address}")
                
                if parsed.get("success"):
                    return ChannelStatsResponse(
                        success=True,
                        status=0,
                        mac_address=parsed.get("mac_address"),
                        modem_ip=parsed.get("modem_ip"),
                        fiber_node=fiber_node,
                        timestamp=parsed.get("timestamp"),
                        timing=parsed.get("timing"),
                        downstream=parsed.get("downstream"),
                        upstream=parsed.get("upstream"),
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
        mac_address: str, community: str
    ) -> str:
        """Lookup fiber node from CMTS using agent SNMP commands."""
        try:
            self.logger.info(f"Looking up fiber node for {mac_address} on CMTS {cmts_ip}")
            
            # Normalize MAC address to match CMTS format (shortened, colons)
            # CMTS stores MACs like 44:5:3f:d4:19:15 (no leading zeros in bytes)
            mac_normalized_parts = []
            mac_clean = mac_address.replace(':', '').replace('-', '').replace('.', '').lower()
            for i in range(0, len(mac_clean), 2):
                byte = mac_clean[i:i+2]
                # Convert to hex without leading zero: '05' -> '5', '0f' -> 'f'
                mac_normalized_parts.append(f"{int(byte, 16):x}")
            mac_normalized = ':'.join(mac_normalized_parts)
            self.logger.info(f"Normalized MAC: {mac_address} -> {mac_normalized}")
            
            # Walk docsIfCmtsCmStatusMacAddress table to find CM index
            oid = '1.3.6.1.2.1.10.127.1.3.3.1.2'  # docsIfCmtsCmStatusMacAddress
            self.logger.info(f"Walking CMTS CM table: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=10.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=10.0)
            self.logger.info(f"SNMP walk result: success={result.get('result',{}).get('success') if result else None}, results_count={len(result.get('result',{}).get('results',[])) if result else 0}")
            
            if not result or not result.get("result", {}).get("success"):
                self.logger.warning(f"Failed to walk CM status table on CMTS {cmts_ip}")
                return None
            
            # Find CM index by matching MAC address
            cm_index = None
            results = result.get("result", {}).get("results", [])
            self.logger.info(f"CMTS returned {len(results)} CMs, looking for {mac_normalized}")
            for entry in results:
                cmts_mac = entry.get("value", "")
                # Normalize CMTS MAC to match format (strip leading zeros from bytes)
                cmts_mac_parts = cmts_mac.split(':')
                cmts_mac_normalized = ':'.join([f"{int(b, 16):x}" if b else '0' for b in cmts_mac_parts])
                self.logger.info(f"Comparing: '{cmts_mac}' (normalized: '{cmts_mac_normalized}') == '{mac_normalized}'")
                if cmts_mac_normalized.lower() == mac_normalized.lower():
                    # Extract index from OID (last component)
                    oid_parts = entry.get("oid", "").split(".")
                    if oid_parts:
                        cm_index = oid_parts[-1]
                        self.logger.info(f"Found CM index {cm_index} for MAC {mac_address}")
                        break
            
            if not cm_index:
                self.logger.warning(f"MAC {mac_address} not found in CMTS table")
                return None
            
            # Get DS ifIndex using CM index
            oid = f'1.3.6.1.2.1.10.127.1.3.3.1.6.{cm_index}'  # docsIfCmtsCmStatusDownChannelIfIndex
            self.logger.info(f"Querying DS ifIndex: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_get", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=5.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=5.0)
            self.logger.info(f"DS ifIndex query result: {result}")
            if not result or not result.get("result", {}).get("success"):
                self.logger.warning(f"Failed to get DS ifIndex for CM index {cm_index}")
                return None
            
            # Get DS ifIndex using CM index - walk parent OID and find our index
            oid = '1.3.6.1.2.1.10.127.1.3.3.1.6'  # docsIfCmtsCmStatusDownChannelIfIndex base
            self.logger.info(f"Walking DS ifIndex table: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=5.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=5.0)
            
            ds_ifindex = None
            if result and result.get("result", {}).get("success"):
                results = result.get("result", {}).get("results", [])
                for entry in results:
                    # OID format: ...1.6.{cm_index}
                    if entry.get("oid", "").endswith(f".{cm_index}"):
                        ds_ifindex = entry.get("value")
                        break
            
            if not ds_ifindex:
                self.logger.warning(f"No DS ifIndex returned for CM index {cm_index}")
                return None
            
            self.logger.info(f"Found DS ifIndex: {ds_ifindex}")
            
            # Walk US-to-DS channel mapping to get MD ifIndex
            # OID: docsIf3MdUsToDsChMappingMdIfIndex
            oid = '1.3.6.1.4.1.4491.2.1.20.1.14.1.3'
            self.logger.info(f"Walking US-to-DS mapping table: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=5.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=5.0)
            
            md_ifindex = None
            if result and result.get("result", {}).get("success"):
                results = result.get("result", {}).get("results", [])
                self.logger.info(f"Got {len(results)} mapping entries")
                # OID format: ...14.1.3.{usIfIndex}.{dsIfIndex}.{mdIfIndex}
                # We're looking for entries with our dsIfIndex
                for entry in results:
                    oid_str = entry.get("oid", "")
                    parts = oid_str.split('.')
                    # The dsIfIndex should be at index -2, mdIfIndex at -1
                    if len(parts) >= 3:
                        entry_ds_ifindex = parts[-2]
                        if entry_ds_ifindex == str(ds_ifindex):
                            md_ifindex = entry.get("value")
                            self.logger.info(f"Found MD ifIndex: {md_ifindex}")
                            break
            
            if not md_ifindex:
                self.logger.warning(f"No MD ifIndex found for DS ifIndex {ds_ifindex}")
                return None
            
            # Now get fiber node name from docsIf3MdNodeStatusMdDsSgId using MD ifIndex
            # OID format: ...1.12.1.{mdIfIndex}."FiberNodeName".{sgId}
            oid = f'1.3.6.1.4.1.4491.2.1.20.1.12.1.{md_ifindex}'
            self.logger.info(f"Walking fiber node table for MD ifIndex {md_ifindex}: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=5.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=5.0)
            
            if result and result.get("result", {}).get("success"):
                results = result.get("result", {}).get("results", [])
                if results:
                    # Extract fiber node name from first entry's OID
                    # OID format: ...1.12.1.{mdIfIndex}."FiberNodeName".{sgId}
                    oid_str = results[0].get("oid", "")
                    parts = oid_str.split('.')
                    # Fiber node name is typically the second-to-last part (before sgId)
                    if len(parts) >= 2:
                        fn_part = parts[-2]
                        fiber_node = fn_part.strip('"')
                        self.logger.info(f"Found fiber node for {mac_address}: {fiber_node}")
                        return fiber_node
                self.logger.warning(f"No fiber node data in mapping for MD ifIndex {md_ifindex}")
            else:
                self.logger.warning(f"Fiber node walk failed for MD ifIndex {md_ifindex}")
            return None
        except Exception as e:
            self.logger.warning(f"Failed to get fiber node: {e}")
            return None


# Router instance for auto-discovery
router = ChannelStatsRouter().router
