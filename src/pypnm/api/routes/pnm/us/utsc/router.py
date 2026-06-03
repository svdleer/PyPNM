# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for CMTS Upstream Triggered Spectrum Capture (UTSC) operations.

This module provides FastAPI endpoints for CMTS-side UTSC measurements.

Endpoints:
- GET  /ports:             List available RF ports for UTSC
- GET  /config:            Get current UTSC configuration
- POST /configure:         Configure UTSC test parameters
- POST /start:             Start UTSC test
- POST /stop:              Stop UTSC test
- POST /clear:             Clear/reset UTSC configuration
- GET  /status:            Get UTSC test status
- POST /files/list:        List UTSC files on agent TFTP
- POST /files/retrieve:    Fetch and parse UTSC file from agent
"""

from __future__ import annotations

import logging
import os
import asyncio
from typing import Any, Optional
from pathlib import Path

from fastapi import APIRouter
from pypnm.api.agent.manager import get_agent_manager

from pypnm.lib.pnm_file_source import (
    fetch_pnm_files as _fetch_pnm_files,
    get_cache_dir as _get_cache_dir,
    is_ftp_mode as _is_ftp_mode,
    local_pnm_dir as _local_pnm_dir,
)

from pypnm.api.routes.pnm.us.utsc.schemas import (
    UtscListPortsRequest,
    UtscListPortsResponse,
    UtscGetConfigRequest,
    UtscGetConfigResponse,
    UtscConfigureRequest,
    UtscConfigureResponse,
    UtscStartRequest,
    UtscStartResponse,
    UtscStopRequest,
    UtscStopResponse,
    UtscStatusRequest,
    UtscStatusResponse,
    UtscFileListRequest,
    UtscFileListResponse,
    UtscFileRetrieveRequest,
    UtscFileRetrieveResponse,
)
from pypnm.api.routes.pnm.us.utsc.service import CmtsUtscService
from pypnm.api.utils.cmts_vendor import (
    get_utsc_filename_pattern,
    CMTSVendor,
)




class UtscRouter:
    """Router for CMTS Upstream Triggered Spectrum Capture operations."""
    
    def __init__(self) -> None:
        prefix = "/pnm/us/utsc"
        self.router = APIRouter(
            prefix=prefix,
            tags=["PNM Operations - CMTS Upstream Triggered Spectrum Capture (UTSC)"]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__routes()
    
    def __routes(self) -> None:
        
        @self.router.get(
            "/ports",
            summary="List RF ports available for UTSC",
            response_model=UtscListPortsResponse,
        )
        async def list_rf_ports(
            cmts_ip: str,
            community: str = "public",
            write_community: Optional[str] = None
        ) -> UtscListPortsResponse:
            """
            List available RF ports for UTSC tests.

            Returns a list of RF port ifIndexes that can be used for
            upstream triggered spectrum capture measurements.
            """
            self.logger.info(f"Listing RF ports on CMTS {cmts_ip}")
            service = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.list_rf_ports()
                return UtscListPortsResponse(**result)
            finally:
                service.close()
        
        @self.router.get(
            "/config",
            summary="Get current UTSC configuration",
            response_model=UtscGetConfigResponse,
        )
        async def get_config(
            cmts_ip: str,
            rf_port_ifindex: int,
            community: str = "public",
            write_community: Optional[str] = None,
            cfg_index: int = 1
        ) -> UtscGetConfigResponse:
            """
            Get current UTSC configuration for an RF port.

            Returns the current settings including trigger mode, frequency range,
            output format, timing parameters, and filename.
            """
            self.logger.info(
                f"Getting UTSC config for RF port {rf_port_ifindex} on CMTS {cmts_ip}"
            )
            service = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.get_config(
                    rf_port_ifindex=rf_port_ifindex,
                    cfg_index=cfg_index
                )
                return UtscGetConfigResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/configure",
            summary="Configure UTSC test parameters",
            response_model=UtscConfigureResponse,
        )
        async def configure(
            request: UtscConfigureRequest
        ) -> UtscConfigureResponse:
            """
            Configure UTSC test parameters.
            
            Sets up the upstream triggered spectrum capture with the specified
            trigger mode, frequency range, output format, timing, and filename.
            
            SNMP OIDs used (docsPnmCmtsUtscCfgTable):
            - docsPnmCmtsUtscCfgTriggerMode: Trigger type (freeRunning, cmMac, etc.)
            - docsPnmCmtsUtscCfgCenterFreq: Center frequency in Hz
            - docsPnmCmtsUtscCfgSpan: Frequency span in Hz
            - docsPnmCmtsUtscCfgNumBins: Number of FFT bins
            - docsPnmCmtsUtscCfgOutputFormat: Output format (fftPower, etc.)
            - docsPnmCmtsUtscCfgRepeatPeriod: Repeat period in microseconds
            - docsPnmCmtsUtscCfgFreeRunDuration: Duration in milliseconds
            - docsPnmCmtsUtscCfgFilename: Output filename
            """
            self.logger.info(
                f"Configuring UTSC for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )

            try:
                # Configure bulk data destination (TFTP upload target) if provided
                if request.tftp_server and request.destination_index > 0:
                    bulk_result = await service.configure_bulk_data_control(
                        dest_ip=request.tftp_server,
                        dest_path=request.dest_path or "./",
                        index=request.destination_index,
                        pnm_types=['utsc'],
                    )
                    if not bulk_result.get('success'):
                        self.logger.warning(
                            f"Bulk dest config failed (continuing): {bulk_result.get('error')}"
                        )
                    else:
                        self.logger.info(
                            f"Bulk dest configured: {request.tftp_server}:{request.dest_path or './'}"
                        )

                result = await service.configure(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index,
                    trigger_mode=request.trigger_mode,
                    cm_mac_address=request.cm_mac_address,
                    logical_ch_ifindex=request.logical_ch_ifindex,
                    center_freq_hz=request.center_freq_hz,
                    span_hz=request.span_hz,
                    num_bins=request.num_bins,
                    output_format=request.output_format,
                    window_function=request.window_function,
                    repeat_period_us=request.repeat_period_us,
                    freerun_duration_ms=request.freerun_duration_ms,
                    trigger_count=request.trigger_count,
                    filename=request.filename,
                    destination_index=request.destination_index
                )
                return UtscConfigureResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/start",
            summary="Start UTSC test",
            response_model=UtscStartResponse,
        )
        async def start(
            request: UtscStartRequest
        ) -> UtscStartResponse:
            """
            Start UTSC test on an RF port.
            
            Sets docsPnmCmtsUtscCtrlInitiateTest to true to begin the
            spectrum capture. Use /status to poll for completion.
            """
            self.logger.info(
                f"Starting UTSC for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.start(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index,
                    trigger_mode=request.trigger_mode
                )
                return UtscStartResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/stop",
            summary="Stop UTSC test",
            response_model=UtscStopResponse,
        )
        async def stop(
            request: UtscStopRequest
        ) -> UtscStopResponse:
            """
            Stop UTSC test on an RF port.
            
            Sets docsPnmCmtsUtscCtrlInitiateTest to false to stop the
            spectrum capture.
            """
            self.logger.info(
                f"Stopping UTSC for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.stop(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index
                )
                return UtscStopResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/clear",
            summary="Clear/reset UTSC configuration",
            response_model=UtscStopResponse,
        )
        async def clear_config(
            request: UtscStopRequest
        ) -> UtscStopResponse:
            """
            Clear/reset UTSC configuration by destroying the row.
            
            Sets docsPnmCmtsUtscCfgRowStatus to destroy(6) to remove
            the configuration entry. Use this to force reconfiguration
            with updated parameters.
            """
            self.logger.info(
                f"Clearing UTSC config for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.clear_config(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index
                )
                return UtscStopResponse(**result)
            finally:
                service.close()
        
        @self.router.get(
            "/status",
            summary="Get UTSC test status",
            response_model=UtscStatusResponse,
        )
        async def get_status(
            cmts_ip: str,
            rf_port_ifindex: int,
            community: str = "public",
            write_community: Optional[str] = None,
            cfg_index: int = 1
        ) -> UtscStatusResponse:
            """
            Get UTSC test status.

            Returns the measurement status, average power, and filename.
            Poll this endpoint after starting a test to check for completion.

            Status values:
            - OTHER (1): Unknown state
            - INACTIVE (2): No test running
            - BUSY (3): Test in progress
            - SAMPLE_READY (4): Test complete, data available
            - ERROR (5): Test failed
            - RESOURCE_UNAVAILABLE (6): Resources not available
            - SAMPLE_TRUNCATED (7): Data was truncated
            """
            self.logger.debug(f"Getting UTSC status for RF port {rf_port_ifindex}")
            service = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.get_status(
                    rf_port_ifindex=rf_port_ifindex,
                    cfg_index=cfg_index
                )
                return UtscStatusResponse(**result)
            finally:
                service.close()
        
        async def _prefetch_via_agent_if_enabled(filename: str) -> bool:
            """Attempt agent-based file prefetch when enabled via environment.

            Enables runtime control from .env:
              - CMTS_TFTP=agent
              - or CMTS_TFTP_UTSC=agent
            """
            mode_cmts = (os.environ.get('CMTS_TFTP', '') or os.environ.get('PNM_FILE_SOURCE_CMTS', '')).strip().lower()
            mode_utsc = (os.environ.get('CMTS_TFTP_UTSC', '') or os.environ.get('PNM_FILE_SOURCE_UTSC', '')).strip().lower()
            if mode_cmts != 'agent' and mode_utsc != 'agent':
                return False

            agent_manager = get_agent_manager()
            if not agent_manager:
                self.logger.warning("Agent prefetch enabled but agent manager is not available")
                return False

            candidate_ids = agent_manager.get_all_agent_ids_for_capability('pnm_file_get')
            if not candidate_ids:
                self.logger.warning("Agent prefetch enabled but no agent with pnm_file_get capability is connected")
                return False

            async def _try_agent(aid: str) -> tuple[str, dict | None]:
                try:
                    tid = await agent_manager.send_task(
                        agent_id=aid,
                        command='file_get',
                        params={'filename': filename, 'glob': True},
                    )
                    res = await agent_manager.wait_for_task_async(
                        tid,
                        timeout=agent_manager.LONG_TASK_TIMEOUT,
                    )
                    return aid, res
                except Exception as exc:
                    self.logger.debug(f"Agent '{aid}' file_get error for '{filename}': {exc}")
                    return aid, None

            pending = {asyncio.ensure_future(_try_agent(aid)): aid for aid in candidate_ids}
            winner: dict | None = None
            winner_agent: str | None = None
            try:
                while pending:
                    done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                    for fut in done:
                        aid, result = fut.result()
                        pending.pop(fut, None)
                        result_inner = (result or {}).get('result') or result or {}
                        if result_inner and result_inner.get('success'):
                            winner = result_inner
                            winner_agent = aid
                            break
                    if winner:
                        break
            finally:
                for fut in pending:
                    fut.cancel()

            if not winner:
                return False

            try:
                import base64
                cache_dir = Path(_get_cache_dir())
                cache_dir.mkdir(parents=True, exist_ok=True)
                out_name = winner.get('filename', Path(filename).name)
                out_path = cache_dir / Path(out_name).name
                out_path.write_bytes(base64.b64decode(winner['content_base64']))
                self.logger.info(f"Agent prefetch succeeded via '{winner_agent}' -> {out_path.name}")
                return True
            except Exception as exc:
                self.logger.warning(f"Agent prefetch decode/write failed for '{filename}': {exc}")
                return False
        
        @self.router.post(
            "/files/list",
            summary="List UTSC files (agent TFTP or direct FTP)",
            response_model=UtscFileListResponse,
        )
        async def list_utsc_files(
            request: UtscFileListRequest
        ) -> UtscFileListResponse:
            """
            List UTSC capture files matching a glob pattern.

            Supports two modes:
            - **Agent/Local (TFTP):** PNM_FILE_SOURCE=agent/local
              Uses agent 'file_list' command to discover files on TFTP server
            - **Direct FTP:** PNM_FILE_SOURCE=ftp
              Lists files from FTP server directly (Casa, CommScope vendors)
            
            The glob pattern can be provided explicitly via 'prefix', or auto-built from:
              - rf_port_ifindex (Cisco pattern: PNMCcapUsSpecAn_*_{ifindex})
              - mac_address (CommScope pattern: utsc_{mac_clean}_*)
            
            Returns filenames only (basenames), so caller can decide which to fetch.
            """
            # Determine prefix to use
            prefix = request.prefix
            if not prefix:
                if request.rf_port_ifindex:
                    prefix = get_utsc_filename_pattern(
                        vendor=CMTSVendor.CISCO,
                        rf_port_ifindex=request.rf_port_ifindex
                    )
                elif request.mac_address:
                    prefix = get_utsc_filename_pattern(
                        vendor=CMTSVendor.COMMSCOPE,
                        mac_address=request.mac_address
                    )
                else:
                    # Default to generic Cisco pattern
                    prefix = "PNMCcapUsSpecAn_*"

            self.logger.debug(f"Listing UTSC files with prefix: {prefix}")

            # FTP mode: scan directly on FTP server
            if _is_ftp_mode():
                import ftplib
                try:
                    from pypnm.lib.pnm_file_source import get_ftp_config
                    ftp_cfg = get_ftp_config()
                    
                    ftp = ftplib.FTP()
                    ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
                    ftp.login(ftp_cfg['user'], ftp_cfg['password'])
                    ftp.cwd(ftp_cfg['ftp_dir'])
                    
                    # Parse prefix into glob pattern (e.g., "PNMCcapUsSpecAn_*_100" → "PNMCcapUsSpecAn_")
                    # Simple pattern: match files starting with prefix up to first wildcard
                    prefix_base = prefix.split('*')[0] if '*' in prefix else prefix
                    
                    all_files = ftp.nlst()
                    matching = [f for f in all_files if f.startswith(prefix_base)]
                    ftp.quit()
                    
                    self.logger.info(f"FTP list found {len(matching)} files matching {prefix}")
                    return UtscFileListResponse(
                        success=True,
                        files=sorted(matching),
                        count=len(matching),
                        prefix_used=prefix
                    )
                except Exception as exc:
                    self.logger.error(f"FTP list error: {exc}")
                    return UtscFileListResponse(
                        success=False,
                        error=f"FTP listing failed: {exc}"
                    )

            # Agent/Local mode: use agent file_list command
            agent_manager = get_agent_manager()
            if not agent_manager:
                return UtscFileListResponse(
                    success=False,
                    error="Agent manager not available (and not in FTP mode)"
                )

            candidate_ids = agent_manager.get_all_agent_ids_for_capability('file_list')
            if not candidate_ids:
                return UtscFileListResponse(
                    success=False,
                    error="No agent with file_list capability is connected"
                )

            # Try agents in parallel, take first result
            async def _try_agent(aid: str) -> tuple[str, dict | None]:
                try:
                    tid = await agent_manager.send_task(
                        agent_id=aid,
                        command='file_list',
                        params={'prefix': prefix},
                    )
                    res = await agent_manager.wait_for_task_async(
                        tid,
                        timeout=30,
                    )
                    return aid, res
                except Exception as exc:
                    self.logger.debug(f"Agent '{aid}' file_list error: {exc}")
                    return aid, None

            pending = {asyncio.ensure_future(_try_agent(aid)): aid for aid in candidate_ids}
            winner: dict | None = None
            winner_agent: str | None = None
            try:
                while pending:
                    done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                    for fut in done:
                        aid, result = fut.result()
                        pending.pop(fut, None)
                        result_inner = (result or {}).get('result') or result or {}
                        if result_inner and result_inner.get('success'):
                            winner = result_inner
                            winner_agent = aid
                            break
                    if winner:
                        break
            finally:
                for fut in pending:
                    fut.cancel()

            if not winner:
                return UtscFileListResponse(
                    success=False,
                    error="No agent returned file_list results"
                )

            return UtscFileListResponse(
                success=True,
                files=winner.get('files', []),
                count=winner.get('count', 0),
                prefix_used=prefix
            )
        
        @self.router.post(
            "/files/retrieve",
            summary="Fetch and parse UTSC file (agent TFTP or direct FTP)",
            response_model=UtscFileRetrieveResponse,
        )
        async def retrieve_utsc_file(
            request: UtscFileRetrieveRequest
        ) -> UtscFileRetrieveResponse:
            """
            Retrieve a UTSC capture file.

            Supports two modes:
            - **Agent/Local (TFTP):** PNM_FILE_SOURCE=agent/local
              Uses agent 'pnm_file_get' command to fetch file content
            - **Direct FTP:** PNM_FILE_SOURCE=ftp
              Downloads file directly from FTP server (Casa, CommScope vendors)
            
            If glob=True, treats filename as a glob pattern and fetches the newest match.
            
            In FTP mode, file is cached in PNM_CACHE_DIR before being returned.
            """
            # FTP mode: download directly from FTP server
            if _is_ftp_mode():
                try:
                    from pypnm.lib.pnm_file_source import get_ftp_config
                    import ftplib
                    ftp_cfg = get_ftp_config()
                    
                    ftp = ftplib.FTP()
                    ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
                    ftp.login(ftp_cfg['user'], ftp_cfg['password'])
                    ftp.cwd(ftp_cfg['ftp_dir'])
                    
                    # If glob=True, find newest file matching pattern
                    if request.glob:
                        prefix_base = request.filename.split('*')[0] if '*' in request.filename else request.filename
                        all_files = ftp.nlst()
                        matching = sorted([f for f in all_files if f.startswith(prefix_base)], reverse=True)
                        if not matching:
                            ftp.quit()
                            return UtscFileRetrieveResponse(
                                success=False,
                                error=f"No FTP files matching pattern: {request.filename}"
                            )
                        actual_filename = matching[0]
                    else:
                        actual_filename = request.filename
                    
                    # Download file to cache
                    cache_dir = Path(_get_cache_dir())
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_path = cache_dir / Path(actual_filename).name
                    
                    with open(cache_path, 'wb') as f:
                        ftp.retrbinary(f'RETR {actual_filename}', f.write)
                    ftp.quit()
                    
                    file_size = cache_path.stat().st_size
                    self.logger.info(f"Retrieved UTSC file via FTP: {actual_filename} ({file_size} bytes) -> {cache_path}")
                    
                    return UtscFileRetrieveResponse(
                        success=True,
                        filename=actual_filename,
                        cache_path=str(cache_path),
                        file_size=file_size,
                        agent_id="ftp"
                    )
                except Exception as exc:
                    self.logger.error(f"FTP retrieval error: {exc}")
                    return UtscFileRetrieveResponse(
                        success=False,
                        error=f"FTP download failed: {exc}"
                    )

            # Agent/Local mode: use agent pnm_file_get command
            agent_manager = get_agent_manager()
            if not agent_manager:
                return UtscFileRetrieveResponse(
                    success=False,
                    error="Agent manager not available"
                )

            candidate_ids = agent_manager.get_all_agent_ids_for_capability('pnm_file_get')
            if not candidate_ids:
                return UtscFileRetrieveResponse(
                    success=False,
                    error="No agent with pnm_file_get capability is connected"
                )

            self.logger.info(f"Retrieving UTSC file: {request.filename} (glob={request.glob})")

            # Try agents in parallel, take first result
            async def _try_agent(aid: str) -> tuple[str, dict | None]:
                try:
                    tid = await agent_manager.send_task(
                        agent_id=aid,
                        command='pnm_file_get',
                        params={'filename': request.filename, 'glob': request.glob},
                        priority='long'
                    )
                    res = await agent_manager.wait_for_task_async(
                        tid,
                        timeout=agent_manager.LONG_TASK_TIMEOUT,
                    )
                    return aid, res
                except Exception as exc:
                    self.logger.debug(f"Agent '{aid}' pnm_file_get error: {exc}")
                    return aid, None

            pending = {asyncio.ensure_future(_try_agent(aid)): aid for aid in candidate_ids}
            winner: dict | None = None
            winner_agent: str | None = None
            try:
                while pending:
                    done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                    for fut in done:
                        aid, result = fut.result()
                        pending.pop(fut, None)
                        result_inner = (result or {}).get('result') or result or {}
                        if result_inner and result_inner.get('success'):
                            winner = result_inner
                            winner_agent = aid
                            break
                    if winner:
                        break
            finally:
                for fut in pending:
                    fut.cancel()

            if not winner:
                return UtscFileRetrieveResponse(
                    success=False,
                    error="No agent returned file_get results"
                )

            try:
                import base64
                cache_dir = Path(_get_cache_dir())
                cache_dir.mkdir(parents=True, exist_ok=True)
                
                filename = winner.get('filename', request.filename)
                content_b64 = winner.get('content_base64')
                
                if not content_b64:
                    return UtscFileRetrieveResponse(
                        success=False,
                        error="Agent returned success but no content_base64"
                    )
                
                out_path = cache_dir / Path(filename).name
                content_bytes = base64.b64decode(content_b64)
                out_path.write_bytes(content_bytes)
                
                self.logger.info(
                    f"Retrieved UTSC file: {filename} ({len(content_bytes)} bytes) "
                    f"via agent '{winner_agent}' -> {out_path.name}"
                )
                
                return UtscFileRetrieveResponse(
                    success=True,
                    filename=filename,
                    cache_path=str(out_path),
                    file_size=len(content_bytes),
                    agent_id=winner_agent
                )
            except Exception as exc:
                self.logger.error(f"Failed to decode/write UTSC file: {exc}")
                return UtscFileRetrieveResponse(
                    success=False,
                    error=f"Decode/write error: {exc}"
                )


# Required for dynamic auto-registration
router = UtscRouter().router
