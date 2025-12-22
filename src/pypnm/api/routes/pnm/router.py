# SPDX-License-Identifier: Apache-2.0
# PNM Common Routes (Modem Diagnostics)

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager
from pypnm.api.routes.pnm.schemas import (
    ChannelInfoRequest,
    ChannelInfoResponse,
    DSChannel,
    USChannel,
    MeasurementStatusResponse,
)
from pypnm.api.routes.pnm.service import PNMDiagnosticsService
from pypnm.api.routes.pnm.measurements import get_measurement_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pnm", tags=["PNM - Common"])


@router.post("/channel-info", response_model=ChannelInfoResponse)
async def get_channel_info(request: ChannelInfoRequest) -> ChannelInfoResponse:
    """
    **Get Comprehensive Channel Info**
    
    Retrieves detailed information for all downstream and upstream channels.
    
    **Downstream (SC-QAM):**
    - Channel ID, frequency, power, SNR
    
    **Downstream (OFDM):**
    - Channel ID, PLC frequency, subcarrier range
    - Active modulation profiles
    - Average power across bands
    
    **Upstream (ATDMA/OFDMA):**
    - Channel ID, transmit power
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Channel info request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.get_channel_info()
        
        if not result.get('success'):
            return ChannelInfoResponse(
                success=False,
                modem_ip=request.modem_ip,
                mac_address=request.mac_address,
                error=result.get('error', 'Channel info query failed')
            )
        
        # Parse downstream channels
        ds_channels = []
        for ch in result.get('downstream', []):
            ds_channels.append(DSChannel(
                channel_id=ch.get('channel_id', 0),
                type=ch.get('type', 'SC-QAM'),
                frequency_mhz=ch.get('frequency_mhz', 0),
                power_dbmv=ch.get('power_dbmv', 0),
                snr_db=ch.get('snr_db'),
                ifindex=ch.get('ifindex'),
                subcarrier_zero_freq_mhz=ch.get('subcarrier_zero_freq_mhz'),
                first_active_subcarrier=ch.get('first_active_subcarrier'),
                last_active_subcarrier=ch.get('last_active_subcarrier'),
                num_active_subcarriers=ch.get('num_active_subcarriers'),
                profiles=ch.get('profiles'),
                current_profile=ch.get('current_profile')
            ))
        
        # Parse upstream channels
        us_channels = []
        for ch in result.get('upstream', []):
            us_channels.append(USChannel(
                channel_id=ch.get('channel_id', 0),
                type=ch.get('type', 'ATDMA'),
                power_dbmv=ch.get('power_dbmv', 0)
            ))
        
        return ChannelInfoResponse(
            success=True,
            mac_address=result.get('mac_address'),
            modem_ip=result.get('modem_ip'),
            timestamp=result.get('timestamp'),
            downstream=ds_channels,
            upstream=us_channels
        )
        
    except Exception as e:
        logger.exception(f"Channel info error: {e}")
        return ChannelInfoResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.get("/measurements/{measurement_id}/status", response_model=MeasurementStatusResponse)
async def get_measurement_status(measurement_id: str) -> MeasurementStatusResponse:
    """
    **Get Async Measurement Status**
    
    Check the status and progress of an async PNM measurement.
    
    **Returns:**
    - Measurement status (in_progress, completed, failed)
    - Progress percentage
    - Results when completed
    """
    manager = get_measurement_manager()
    measurement = manager.get_measurement_status(measurement_id)
    
    if not measurement:
        raise HTTPException(status_code=404, detail=f"Measurement {measurement_id} not found")
    
    return MeasurementStatusResponse(
        measurement_id=measurement.measurement_id,
        status=measurement.status,
        progress=measurement.progress,
        started_at=measurement.started_at.isoformat(),
        completed_at=measurement.completed_at.isoformat() if measurement.completed_at else None,
        estimated_completion=measurement.estimated_completion.isoformat(),
        error=measurement.error,
        measurements=measurement.measurements,
        filename=measurement.filename,
        mac_address=measurement.mac_address,
        modem_ip=measurement.modem_ip
    )
