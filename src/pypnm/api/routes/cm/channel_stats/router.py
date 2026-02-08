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
                # Send task to agent
                task_id = await agent_manager.send_task(
                    agent_id,
                    "pnm_channel_stats",
                    {
                        "modem_ip": request.modem_ip,
                        "mac_address": request.mac_address,
                        "community": request.community,
                        "cmts_ip": request.cmts_ip,
                        "cmts_community": request.cmts_community,
                        "skip_connectivity_check": request.skip_connectivity_check,
                    },
                    timeout=30.0
                )
                
                # Wait for result
                result = await agent_manager.wait_for_task_async(task_id, timeout=30.0)
                
                if not result:
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error="Agent task timed out"
                    )
                
                # Result is wrapped: {request_id, result: {...}, error: ...}
                # Extract the actual result from the agent
                agent_result = result.get("result", {})
                
                if agent_result.get("success"):
                    return ChannelStatsResponse(
                        success=True,
                        status=0,
                        mac_address=agent_result.get("mac_address"),
                        modem_ip=agent_result.get("modem_ip"),
                        timestamp=agent_result.get("timestamp"),
                        timing=agent_result.get("timing"),
                        downstream=agent_result.get("downstream"),
                        upstream=agent_result.get("upstream"),
                    )
                else:
                    return ChannelStatsResponse(
                        success=False,
                        status=-1,
                        error=agent_result.get("error") or result.get("error") or "Unknown error from agent"
                    )
                    
            except ValueError as e:
                self.logger.error(f"Agent error: {e}")
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                self.logger.error(f"Channel stats failed: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get channel stats: {str(e)}")


# Router instance for auto-discovery
router = ChannelStatsRouter().router
