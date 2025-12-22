# SPDX-License-Identifier: Apache-2.0
# PNM Downstream Diagnostics Router

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager
from pypnm.api.routes.pnm.schemas import (
    PNMModemRequest,
    RxMERResponse,
    FECResponse,
    ChannelPowerResponse,
    SpectrumRequest,
    SpectrumResponse,
    ChannelEstimationRequest,
    ChannelEstimationResponse,
    ModulationProfileRequest,
    ModulationProfileResponse,
    HistogramRequest,
    HistogramResponse,
    ConstellationRequest,
    ConstellationResponse,
    AsyncMeasurementResponse,
)
from pypnm.api.routes.pnm.service import PNMDiagnosticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pnm/ds", tags=["PNM - Downstream"])


@router.post("/rxmer", response_model=RxMERResponse)
async def get_rxmer(request: PNMModemRequest) -> RxMERResponse:
    """
    **Get RxMER (Receive Modulation Error Ratio)**
    
    Retrieves RxMER measurements from a cable modem.
    RxMER indicates the quality of the received signal on OFDM channels.
    
    **Returns:**
    - Per-channel MER values in dB
    - Higher values indicate better signal quality
    - Typical good values: > 35 dB
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"RxMER request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.get_rxmer()
        return RxMERResponse(**result)
    except Exception as e:
        logger.exception(f"RxMER error: {e}")
        return RxMERResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.post("/rxmer/async", response_model=AsyncMeasurementResponse)
async def start_rxmer_async(request: PNMModemRequest) -> AsyncMeasurementResponse:
    """
    **Start Async RxMER Measurement**
    
    Starts an asynchronous RxMER measurement and returns immediately with a measurement ID.
    Use the measurement ID to check status and retrieve results.
    
    **Workflow:**
    1. Triggers RxMER measurement on the modem
    2. Returns measurement ID immediately  
    3. Modem completes measurement (~30 seconds)
    4. Check status via `/pnm/measurements/{id}/status`
    5. Results available when status = "completed"
    
    **Returns:**
    - measurement_id: Use to check status
    - status: "in_progress" 
    - estimated_completion: When measurement should complete
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Starting async RxMER for modem {request.modem_ip}")
    
    # Start the measurement trigger
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        # Trigger the measurement (this should return quickly)
        await service.trigger_rxmer_measurement()
        
        # Register with measurement manager
        manager = get_measurement_manager()
        measurement_id = manager.start_measurement(
            measurement_type="rxmer",
            mac_address=request.mac_address or "unknown",
            modem_ip=request.modem_ip,
            community=request.community
        )
        
        measurement = manager.get_measurement_status(measurement_id)
        
        return AsyncMeasurementResponse(
            measurement_id=measurement_id,
            status=measurement.status,
            estimated_completion=measurement.estimated_completion.isoformat(),
            progress=measurement.progress,
            message="RxMER measurement started"
        )
        
    except Exception as e:
        logger.exception(f"Async RxMER error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start RxMER measurement: {e}")


@router.post("/fec", response_model=FECResponse)
async def get_fec(request: PNMModemRequest) -> FECResponse:
    """
    **Get FEC (Forward Error Correction) Statistics**
    
    Retrieves FEC codeword statistics from a cable modem.
    
    **Returns per channel:**
    - Unerrored codewords (received correctly)
    - Corrected codewords (had errors, but corrected by FEC)
    - Uncorrectable codewords (errors too severe to correct)
    - SNR (Signal-to-Noise Ratio)
    
    **Health indicators:**
    - High uncorrectable count indicates signal problems
    - Ratio of corrected/uncorrectable useful for trend analysis
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"FEC request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.get_fec()
        return FECResponse(**result)
    except Exception as e:
        logger.exception(f"FEC error: {e}")
        return FECResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.post("/channel-power", response_model=ChannelPowerResponse)
async def get_channel_power(request: PNMModemRequest) -> ChannelPowerResponse:
    """
    **Get Downstream Channel Power Data**
    
    Retrieves downstream channel power levels from a cable modem.
    
    **Returns:**
    - Channel frequency in Hz
    - Receive power in dBmV
    - Typical good range: -7 to +7 dBmV
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Channel power request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.get_channel_power()
        return ChannelPowerResponse(**result)
    except Exception as e:
        logger.exception(f"Channel power error: {e}")
        return ChannelPowerResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.post("/spectrum", response_model=SpectrumResponse)
async def trigger_spectrum(request: SpectrumRequest) -> SpectrumResponse:
    """
    **Trigger Spectrum Analyzer Capture**
    
    Triggers a full-band downstream spectrum capture on a cable modem.
    The modem performs the capture and uploads to the configured TFTP server.
    
    **Process:**
    1. Configure TFTP destination on modem
    2. Set spectrum analyzer parameters
    3. Enable capture (triggers measurement)
    4. Modem uploads file to TFTP
    
    **Returns:**
    - Filename of captured data
    - Use file retrieval endpoints to get the spectrum data
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Spectrum capture request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.trigger_spectrum(tftp_server=request.tftp_server)
        return SpectrumResponse(**result)
    except Exception as e:
        logger.exception(f"Spectrum capture error: {e}")
        return SpectrumResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )

@router.post("/channel-estimation", response_model=ChannelEstimationResponse)
async def get_channel_estimation(request: ChannelEstimationRequest) -> ChannelEstimationResponse:
    """
    **Get OFDM Channel Estimation Coefficients**
    
    Triggers channel estimation coefficient measurement on the cable modem.
    These coefficients help identify linear distortions, group delay, and reflections.
    
    **Process:**
    1. Set TFTP server on modem
    2. Trigger channel estimation test (test type 4)
    3. Wait for completion and file upload
    4. Parse coefficient data
    
    **Returns:**
    - Per-channel coefficient arrays
    - Frequency information
    - Generated filename for raw data
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Channel estimation request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        # Use the PNM spectrum service as a base - we'll add specific channel estimation logic
        result = await service.trigger_pnm_measurement(
            test_type=4,  # DS_OFDM_CHAN_EST_COEF
            tftp_server=request.tftp_server,
            channel_ids=request.channel_ids
        )
        return ChannelEstimationResponse(**result)
    except Exception as e:
        logger.exception(f"Channel estimation error: {e}")
        return ChannelEstimationResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.post("/modulation-profile", response_model=ModulationProfileResponse)
async def get_modulation_profile(request: ModulationProfileRequest) -> ModulationProfileResponse:
    """
    **Get OFDM Modulation Profile**
    
    Retrieves the OFDM modulation profile configuration for downstream channels.
    Shows which subcarriers use which modulation levels (BPSK, QPSK, QAM16, etc.)
    
    **Process:**
    1. Set TFTP server on modem
    2. Trigger modulation profile test (test type 10)
    3. Parse profile data
    
    **Returns:**
    - Per-channel modulation profiles
    - Active profile information
    - Subcarrier-to-modulation mapping
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Modulation profile request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.trigger_pnm_measurement(
            test_type=10,  # DS_OFDM_MODULATION_PROFILE
            tftp_server=request.tftp_server,
            channel_ids=request.channel_ids
        )
        return ModulationProfileResponse(**result)
    except Exception as e:
        logger.exception(f"Modulation profile error: {e}")
        return ModulationProfileResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.post("/histogram", response_model=HistogramResponse)
async def get_histogram(request: HistogramRequest) -> HistogramResponse:
    """
    **Get Downstream Signal Histogram**
    
    Captures signal level histogram data from the cable modem.
    Useful for analyzing signal distribution and identifying intermittent issues.
    
    **Process:**
    1. Set TFTP server on modem
    2. Trigger histogram measurement (test type 8)
    3. Parse histogram bin data
    
    **Returns:**
    - Per-channel histogram bins and counts
    - Total sample counts
    - Signal distribution statistics
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Histogram request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.trigger_pnm_measurement(
            test_type=8,  # DS_HISTOGRAM
            tftp_server=request.tftp_server,
            channel_ids=request.channel_ids
        )
        return HistogramResponse(**result)
    except Exception as e:
        logger.exception(f"Histogram error: {e}")
        return HistogramResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


@router.post("/constellation", response_model=ConstellationResponse)
async def get_constellation(request: ConstellationRequest) -> ConstellationResponse:
    """
    **Get Constellation Display Data**
    
    Captures constellation points for downstream OFDM channels.
    Shows the I/Q scatter plot data used for signal quality analysis.
    
    **Process:**
    1. Set TFTP server on modem
    2. Trigger constellation display test (test type 5)
    3. Parse I/Q point data
    
    **Returns:**
    - Per-channel constellation points (I/Q coordinates)
    - Modulation type information
    - Associated MER measurements
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Constellation display request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.trigger_pnm_measurement(
            test_type=5,  # DS_CONSTELLATION_DISP
            tftp_server=request.tftp_server,
            channel_ids=request.channel_ids
        )
        return ConstellationResponse(**result)
    except Exception as e:
        logger.exception(f"Constellation display error: {e}")
        return ConstellationResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )