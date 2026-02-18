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
    fiber_node: Optional[str] = None
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
                    '1.3.6.1.4.1.4491.2.1.28.1.2',  # docsIf31RxChStatusTable (OFDM profiles)
                    '1.3.6.1.4.1.4491.2.1.28.1.10', # docsIf31CmDsOfdmProfileStatsTable (OFDM codewords)
                    '1.3.6.1.2.1.10.127.1.1.2',     # docsIfUpChannelTable
                    '1.3.6.1.4.1.4491.2.1.20.1.2',  # docsIf3CmStatusUsTable
                    '1.3.6.1.4.1.4491.2.1.28.1.13', # docsIf31CmUsOfdmaChanTable
                    '1.3.6.1.4.1.4491.2.1.28.1.12', # docsIf31CmStatusOfdmaUsTable
                    '1.3.6.1.4.1.4491.2.1.28.1.14', # docsIf31CmUsOfdmaProfileStatsTable (OFDMA IUC stats)
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
                
                # Send modem parallel walk task
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

                # Concurrently send CMTS OFDMA walk + fiber node lookup tasks
                # (Cisco modems return empty modem-side OFDMA; CMTS walk runs in
                # parallel so it adds zero extra wall-clock time)
                cmts_ofdma_task_id = None
                if request.cmts_ip:
                    try:
                        cmts_ofdma_task_id = await agent_manager.send_task(
                            agent_id, "snmp_walk",
                            {
                                "target_ip": request.cmts_ip,
                                "oid": '1.3.6.1.4.1.4491.2.1.28.1.4',  # docsIf31CmtsUsOfdmaChanTable
                                "community": request.cmts_community or "public",
                            },
                            timeout=15.0,
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to send CMTS OFDMA task: {e}")

                # Wait for modem walk result
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

                # Collect CMTS OFDMA result (already running in parallel)
                ofdma_oid = '1.3.6.1.4.1.4491.2.1.28.1.13'
                modem_ofdma_empty = not raw_results.get(ofdma_oid)
                if modem_ofdma_empty and cmts_ofdma_task_id:
                    try:
                        cmts_result = await agent_manager.wait_for_task_async(cmts_ofdma_task_id, timeout=15.0)
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

                # Fiber node lookup (also runs concurrently via asyncio.gather)
                fiber_node = None
                if request.cmts_ip and request.mac_address:
                    fiber_node = await self._get_fiber_node_from_cmts(
                        agent_manager, agent_id, request.cmts_ip,
                        request.mac_address, request.cmts_community or "public"
                    )
                
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
            
            # Get CM's Service Group ID - needed to match fiber node
            oid = '1.3.6.1.4.1.4491.2.1.20.1.3.1.8'  # docsIf3CmtsCmRegStatusMdCmSgId base
            self.logger.info(f"Walking CM Service Group ID table: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=5.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=5.0)
            
            cm_sg_id = None
            if result and result.get("result", {}).get("success"):
                results = result.get("result", {}).get("results", [])
                for entry in results:
                    oid_str = entry.get("oid", "")
                    # OID format: ...1.3.1.4.{cm_index}
                    parts = oid_str.split('.')
                    if parts and parts[-1] == str(cm_index):
                        cm_sg_id = entry.get("value")
                        break
            
            if not cm_sg_id:
                self.logger.warning(f"No Service Group ID found for CM index {cm_index}")
                return None
            
            self.logger.info(f"Found CM Service Group ID: {cm_sg_id}")
            
            # Walk the full fiber node table and match by SG ID directly
            # This approach works for both E6000 and Cisco without needing US/DS ifIndex mapping
            # OID format: ...1.12.1.3.{mdIfIndex}.{length}.{ASCII bytes of FN name}.{sgId} = Gauge32: {dsSgId}
            oid = '1.3.6.1.4.1.4491.2.1.20.1.12.1.3'  # docsIf3MdNodeStatusMdDsSgId
            self.logger.info(f"Walking full fiber node table to find SG ID {cm_sg_id}: {oid}")
            task_id = await agent_manager.send_task(agent_id, "snmp_walk", {"target_ip": cmts_ip, "oid": oid, "community": community}, timeout=10.0)
            result = await agent_manager.wait_for_task_async(task_id, timeout=10.0)
            
            if result and result.get("result", {}).get("success"):
                results = result.get("result", {}).get("results", [])
                self.logger.info(f"Fiber node table has {len(results)} entries, searching for SG ID {cm_sg_id}")
                
                # Find fiber node by matching SG ID in the OID index
                # OID format: ...1.12.1.3.{mdIfIndex}.{length}.{ASCII bytes of FN name}.{sgId}
                for entry in results:
                    oid_str = entry.get("oid", "")
                    
                    # Check if OID ends with our SG ID
                    if oid_str.endswith(f".{cm_sg_id}"):
                        # Parse fiber node name from OID
                        # Format: ...{mdIfIndex}.{length}.{ASCII bytes}.{sgId}
                        parts = oid_str.split('.')
                        try:
                            # Find the length field (should be after mdIfIndex)
                            # Walk backwards from sgId to find the name
                            sg_id_pos = len(parts) - 1
                            
                            # The structure before sgId is: mdIfIndex.length.char1.char2...charN
                            # We need to find the length to know how many chars to read
                            # Try to find it by looking for a small number (name length) followed by ASCII values
                            for i in range(sg_id_pos - 1, 1, -1):
                                potential_length = int(parts[i])
                                if 1 <= potential_length <= 50:  # Reasonable name length
                                    # Check if next N parts are valid ASCII
                                    ascii_parts = parts[i+1:i+1+potential_length]
                                    if len(ascii_parts) == potential_length:
                                        try:
                                            ascii_values = [int(p) for p in ascii_parts]
                                            if all(32 <= v <= 126 for v in ascii_values):  # Printable ASCII
                                                fiber_node = ''.join(chr(v) for v in ascii_values)
                                                self.logger.info(f"Found fiber node for {mac_address}: {fiber_node} (SG ID: {cm_sg_id})")
                                                return fiber_node
                                        except ValueError:
                                            continue
                            
                            self.logger.warning(f"Could not parse fiber node name from OID {oid_str}")
                        except (ValueError, IndexError) as e:
                            self.logger.warning(f"Failed to parse fiber node from OID {oid_str}: {e}")
                            continue
                
                self.logger.warning(f"No fiber node found matching SG ID {cm_sg_id}")
            else:
                self.logger.warning(f"Fiber node table walk failed")
            return None
        except Exception as e:
            self.logger.warning(f"Failed to get fiber node: {e}")
            return None


# Router instance for auto-discovery
router = ChannelStatsRouter().router
