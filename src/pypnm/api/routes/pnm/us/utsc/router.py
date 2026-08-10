# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for CMTS Upstream Triggered Spectrum Capture (UTSC) operations.

This module provides FastAPI endpoints for CMTS-side UTSC measurements.

Endpoints:
- GET  /ports:                 List available RF ports for UTSC
- GET  /config:                Get current UTSC configuration
- POST /configure:             Configure UTSC test parameters
- POST /start:                 Start UTSC test
- POST /stop:                  Stop UTSC test
- POST /clear:                 Clear/reset UTSC configuration
- GET  /status:                Get UTSC test status
- POST /files/list:            List captures from the authoritative source
- POST /files/retrieve:        Retrieve one raw capture into PyPNM
- POST /files/sample:          Return normalized spectrum samples
- POST /files/delete:          Delete named captures
- POST /files/housekeeping:    Delete aged captures safely
"""

from __future__ import annotations

import logging
import os
import stat
import fnmatch
import asyncio
from typing import Any, Optional
from pathlib import Path

from fastapi import APIRouter
from pypnm.api.agent.manager import get_agent_manager

from pypnm.lib.pnm_file_source import (
    delete_pnm_files as _delete_pnm_files,
    get_cache_dir as _get_cache_dir,
    get_ftp_config as _get_ftp_config,
    get_tftp_dest_path as _get_tftp_dest_path,
    get_tftp_server as _get_tftp_server,
    housekeeping_pnm_files as _housekeeping_pnm_files,
    list_pnm_files as _list_pnm_files,
    local_pnm_dir as _local_pnm_dir,
    resolve_file_mode as _resolve_file_mode,
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
    UtscSampleRequest,
    UtscSampleResponse,
    UtscFileDeleteRequest,
    UtscFileDeleteResponse,
    UtscHousekeepingRequest,
    UtscHousekeepingResponse,
)
from pypnm.api.routes.pnm.us.utsc.service import CmtsUtscService
from pypnm.api.utils.cmts_vendor import (
    get_utsc_filename_pattern,
    CMTSVendor,
)


def _select_file_agent(agent_manager: Any, capability: str, requested: str | None = None) -> str | None:
    """Select one capable file agent; destructive operations are never fanned out."""
    capable = agent_manager.get_all_agent_ids_for_capability(capability)
    if requested:
        return requested if requested in capable else None
    preferred = [agent_id for agent_id in capable if agent_id.startswith('file-agent')]
    candidates = preferred or capable
    return candidates[0] if candidates else None


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

        def _resolve_utsc_file_mode(vendor: Optional[str] = None) -> str:
            return _resolve_file_mode(vendor)
        
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
                # PyPNM owns vendor detection and upload destination policy.
                if request.destination_index > 0:
                    vendor = await service.detect_vendor()
                    tftp_server = request.tftp_server or _get_tftp_server(vendor)
                    dest_path = request.dest_path or _get_tftp_dest_path(vendor)
                    bulk_result = await service.configure_bulk_data_control(
                        dest_ip=tftp_server,
                        dest_path=dest_path,
                        index=request.destination_index,
                        pnm_types=['utsc'],
                    )
                    if not bulk_result.get('success'):
                        self.logger.warning(
                            "Bulk dest config failed (continuing): %s",
                            bulk_result.get('error'),
                        )
                    else:
                        self.logger.info("UTSC bulk destination configured for vendor=%s", vendor)

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
            mode = _resolve_utsc_file_mode(request.vendor)
            self.logger.info(
                f"UTSC file_list request for cmts={request.rf_port_ifindex or 'n/a'} vendor={request.vendor or 'unknown'} mode={mode}"
            )
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

            # PyPNM owns direct FTP and local source listing.
            if mode in ('ftp', 'local'):
                try:
                    matching = _list_pnm_files(
                        prefix,
                        vendor=request.vendor,
                        exclude=request.exclude,
                    )
                    return UtscFileListResponse(
                        success=True,
                        files=matching,
                        count=len(matching),
                        prefix_used=prefix,
                    )
                except Exception as exc:
                    self.logger.error("UTSC %s list error: %s", mode, exc)
                    return UtscFileListResponse(
                        success=False,
                        error=f"{mode.upper()} listing failed: {exc}",
                    )

            # Agent mode: use agent file_list command
            agent_manager = get_agent_manager()
            if not agent_manager:
                return UtscFileListResponse(
                    success=False,
                    error="Agent manager not available (and not in FTP mode)"
                )

            # Only file-agents have TFTP root access; cmts/cm agents do not.
            all_capable = agent_manager.get_all_agent_ids_for_capability('file_list')
            candidate_ids = [a for a in all_capable if a.startswith('file-agent')]
            if not candidate_ids:
                candidate_ids = all_capable  # fallback if no file-agent connected
            if not candidate_ids:
                return UtscFileListResponse(
                    success=False,
                    error="No agent with file_list capability is connected"
                )

            self.logger.info(
                f"UTSC file_list using agent mode via {len(candidate_ids)} candidate(s) for prefix={prefix}"
            )

            # Agent file_list accepts a literal prefix, not an unsafe glob. Ask
            # for the stable portion and apply the original pattern in PyPNM.
            agent_pattern = Path(prefix).name
            if (
                agent_pattern != prefix
                or '\x00' in agent_pattern
                or any(char in agent_pattern for char in ('?', '[', ']'))
            ):
                return UtscFileListResponse(
                    success=False,
                    error="Agent listing accepts basename patterns with '*' only",
                )
            agent_prefix = agent_pattern.split('*', 1)[0]

            # Try agents in parallel, take first result
            async def _try_agent(aid: str) -> tuple[str, dict | None]:
                try:
                    tid = await agent_manager.send_task(
                        agent_id=aid,
                        command='file_list',
                        params={'prefix': agent_prefix},
                        priority='interactive',
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

            raw_files: list[str] = [
                Path(name).name
                for name in (winner.get('files', []) or [])
                if fnmatch.fnmatch(Path(name).name, agent_pattern)
            ]
            # Filter out basenames the caller already has so they don't re-fetch them.
            exclude_set: set[str] = {
                os.path.basename(f) for f in (request.exclude or [])
            }
            if exclude_set:
                raw_files = [f for f in raw_files if os.path.basename(f) not in exclude_set]
            return UtscFileListResponse(
                success=True,
                files=raw_files,
                count=len(raw_files),
                prefix_used=prefix,
                agent_id=winner_agent,
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
            mode = _resolve_utsc_file_mode(request.vendor)
            self.logger.info(
                f"UTSC file_retrieve request filename={request.filename} vendor={request.vendor or 'unknown'} mode={mode} glob={request.glob}"
            )

            # Cache-hit: if file already exists locally, return it without agent/FTP call.
            if not request.glob:
                cache_dir = Path(_get_cache_dir())
                cache_path = cache_dir / Path(request.filename).name
                if cache_path.exists():
                    import base64 as _b64
                    content_bytes = cache_path.read_bytes()
                    self.logger.info(
                        f"UTSC file_retrieve cache hit: {cache_path.name} ({len(content_bytes)} bytes)"
                    )
                    return UtscFileRetrieveResponse(
                        success=True,
                        filename=cache_path.name,
                        cache_path=str(cache_path),
                        file_size=len(content_bytes),
                        agent_id='cache',
                        content_base64=_b64.b64encode(content_bytes).decode(),
                    )

            # FTP mode: download directly into PyPNM's cache.
            if mode == 'ftp':
                import base64
                import ftplib
                import fnmatch

                ftp = None
                try:
                    ftp_cfg = _get_ftp_config(request.vendor)
                    ftp = ftplib.FTP()
                    ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
                    ftp.login(ftp_cfg['user'], ftp_cfg['password'])
                    ftp.cwd(ftp_cfg['ftp_dir'])
                    actual_filename = request.filename
                    if request.glob:
                        matching = [
                            name for name in ftp.nlst()
                            if fnmatch.fnmatch(Path(name).name, Path(request.filename).name)
                        ]
                        if not matching:
                            return UtscFileRetrieveResponse(
                                success=False,
                                error=f"No FTP files matching pattern: {request.filename}",
                            )
                        actual_filename = sorted(matching, reverse=True)[0]

                    cache_path = Path(_get_cache_dir()) / Path(actual_filename).name
                    temp_path = cache_path.with_suffix(cache_path.suffix + '.part')
                    try:
                        with temp_path.open('wb') as handle:
                            ftp.retrbinary(f'RETR {actual_filename}', handle.write)
                        temp_path.replace(cache_path)
                    finally:
                        temp_path.unlink(missing_ok=True)
                    content_bytes = cache_path.read_bytes()
                    return UtscFileRetrieveResponse(
                        success=True,
                        filename=cache_path.name,
                        cache_path=str(cache_path),
                        file_size=len(content_bytes),
                        agent_id='ftp',
                        content_base64=base64.b64encode(content_bytes).decode(),
                    )
                except Exception as exc:
                    self.logger.error("FTP retrieval error: %s", exc)
                    return UtscFileRetrieveResponse(success=False, error=f"FTP download failed: {exc}")
                finally:
                    if ftp is not None:
                        try:
                            ftp.quit()
                        except Exception:
                            pass

            if mode == 'local':
                import base64
                import fnmatch

                pattern = Path(request.filename).name
                candidates = [
                    path for path in _local_pnm_dir(request.vendor).rglob('*')
                    if path.is_file() and (
                        fnmatch.fnmatch(path.name, pattern) if request.glob else path.name == pattern
                    )
                ]
                if not candidates:
                    return UtscFileRetrieveResponse(
                        success=False,
                        error=f"No local files matching: {request.filename}",
                    )
                selected = max(candidates, key=lambda path: path.stat().st_mtime)
                content_bytes = selected.read_bytes()
                return UtscFileRetrieveResponse(
                    success=True,
                    filename=selected.name,
                    file_size=len(content_bytes),
                    agent_id='local',
                    content_base64=base64.b64encode(content_bytes).decode(),
                )

            # Agent mode: use agent pnm_file_get command
            agent_manager = get_agent_manager()
            if not agent_manager:
                return UtscFileRetrieveResponse(
                    success=False,
                    error="Agent manager not available"
                )

            # Resolve agent-mode glob requests through the safe list contract,
            # then retrieve one exact basename. pnm_file_get never accepts globs.
            agent_filename = request.filename
            source_agent: str | None = None
            if request.glob:
                listed = await list_utsc_files(UtscFileListRequest(
                    prefix=request.filename,
                    vendor=request.vendor,
                ))
                if not listed.success or not listed.files:
                    return UtscFileRetrieveResponse(
                        success=False,
                        error=listed.error or f"No agent files matching: {request.filename}",
                    )
                agent_filename = sorted(listed.files, reverse=True)[0]
                source_agent = listed.agent_id

            # Only file-agents have TFTP root access; cmts/cm agents do not.
            all_capable = agent_manager.get_all_agent_ids_for_capability('pnm_file_get')
            candidate_ids = [a for a in all_capable if a.startswith('file-agent')]
            if not candidate_ids:
                candidate_ids = all_capable  # fallback if no file-agent connected
            if source_agent in candidate_ids:
                candidate_ids = [source_agent]
            if not candidate_ids:
                return UtscFileRetrieveResponse(
                    success=False,
                    error="No agent with pnm_file_get capability is connected"
                )

            self.logger.info(
                f"UTSC file_retrieve using agent mode via {len(candidate_ids)} candidate(s) for filename={agent_filename}"
            )

            self.logger.info(f"Retrieving exact UTSC file: {agent_filename}")

            # Read-only retrieval may try equivalent file agents in parallel,
            # except when a prior list response established source affinity.
            async def _try_agent(aid: str) -> tuple[str, dict | None]:
                try:
                    tid = await agent_manager.send_task(
                        agent_id=aid,
                        command='pnm_file_get',
                        params={'filename': agent_filename},
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
                
                filename = winner.get('filename', agent_filename)
                content_b64 = winner.get('content_base64')
                
                if not content_b64:
                    return UtscFileRetrieveResponse(
                        success=False,
                        error="Agent returned success but no content_base64"
                    )
                
                out_path = cache_dir / Path(filename).name
                content_bytes = base64.b64decode(content_b64)
                temp_path = out_path.with_suffix(out_path.suffix + '.part')
                try:
                    temp_path.write_bytes(content_bytes)
                    temp_path.replace(out_path)
                finally:
                    temp_path.unlink(missing_ok=True)
                
                self.logger.info(
                    f"Retrieved UTSC file: {filename} ({len(content_bytes)} bytes) "
                    f"via agent '{winner_agent}' -> {out_path.name}"
                )
                
                return UtscFileRetrieveResponse(
                    success=True,
                    filename=filename,
                    cache_path=str(out_path),
                    file_size=len(content_bytes),
                    agent_id=winner_agent,
                    content_base64=content_b64
                )
            except Exception as exc:
                self.logger.error(f"Failed to decode/write UTSC file: {exc}")
                return UtscFileRetrieveResponse(
                    success=False,
                    error=f"Decode/write error: {exc}"
                )

        @self.router.post(
            "/files/sample",
            summary="Retrieve and normalize a UTSC spectrum sample",
            response_model=UtscSampleResponse,
        )
        async def get_utsc_sample(request: UtscSampleRequest) -> UtscSampleResponse:
            import base64
            import time
            from pypnm.pnm.parser.utsc_file import parse_utsc_file

            retrieved = await retrieve_utsc_file(UtscFileRetrieveRequest(
                filename=request.filename,
                glob=request.glob,
                vendor=request.vendor,
            ))
            if not retrieved.success or not retrieved.content_base64:
                return UtscSampleResponse(
                    success=False,
                    error=retrieved.error or "UTSC file retrieval returned no content",
                )
            try:
                content = base64.b64decode(retrieved.content_base64)
                sample = parse_utsc_file(
                    content,
                    filename=retrieved.filename or Path(request.filename).name,
                    vendor=request.vendor,
                    center_freq_hz=request.center_freq_hz,
                    span_hz=request.span_hz,
                    max_bins=request.max_bins,
                )
                return UtscSampleResponse(
                    success=True,
                    collected_at=time.time(),
                    source=retrieved.agent_id,
                    **sample,
                )
            except Exception as exc:
                self.logger.warning("UTSC sample parse failed for %s: %s", request.filename, exc)
                return UtscSampleResponse(success=False, error=str(exc))

        @self.router.post(
            "/files/delete",
            summary="Delete named UTSC capture files",
            response_model=UtscFileDeleteResponse,
        )
        async def delete_utsc_files(
            request: UtscFileDeleteRequest,
        ) -> UtscFileDeleteResponse:
            mode = _resolve_file_mode(request.vendor)
            try:
                if mode != 'agent':
                    deleted = 0
                    for filename in request.filenames:
                        deleted += _delete_pnm_files(
                            filename,
                            vendor=request.vendor,
                            include_local_source=True,
                        )
                    return UtscFileDeleteResponse(success=True, deleted_count=deleted)

                agent_manager = get_agent_manager()
                if not agent_manager:
                    return UtscFileDeleteResponse(
                        success=False,
                        error="Agent manager not available",
                    )
                agent_id = _select_file_agent(
                    agent_manager,
                    'pnm_file_delete',
                    request.agent_id,
                )
                if not agent_id:
                    detail = (
                        "Requested agent does not advertise pnm_file_delete"
                        if request.agent_id
                        else "No agent with pnm_file_delete capability is connected"
                    )
                    return UtscFileDeleteResponse(success=False, error=detail)

                task_id = await agent_manager.send_task(
                    agent_id=agent_id,
                    command='pnm_file_delete',
                    params={'filenames': request.filenames},
                    timeout=agent_manager.LONG_TASK_TIMEOUT,
                    priority='long',
                )
                result = await agent_manager.wait_for_task_async(
                    task_id,
                    timeout=agent_manager.LONG_TASK_TIMEOUT,
                )
                inner = (result or {}).get('result') or result or {}
                deleted_names = [
                    filename
                    for filename in (inner.get('files') or [])
                    if filename in request.filenames
                ]
                if inner.get('success') and not deleted_names:
                    # An idempotent remote delete may report zero because the
                    # authoritative file was already absent; its cache is stale.
                    deleted_names = request.filenames
                if deleted_names:
                    # The agent is authoritative; remove only corresponding local
                    # cache entries without treating cache cleanup as another delete.
                    for filename in deleted_names:
                        cache_path = Path(_get_cache_dir()) / filename
                        try:
                            cache_stat = os.lstat(cache_path)
                            if stat.S_ISREG(cache_stat.st_mode) and not stat.S_ISLNK(cache_stat.st_mode):
                                cache_path.unlink()
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            self.logger.warning("UTSC cache cleanup refused for %s: %s", filename, exc)
                return UtscFileDeleteResponse(
                    success=bool(inner.get('success')),
                    deleted_count=int(inner.get('deleted_count') or 0),
                    files=inner.get('files') or [],
                    errors=inner.get('errors') or [],
                    truncated=bool(inner.get('truncated', False)),
                    agent_id=agent_id,
                    error=inner.get('error'),
                )
            except Exception as exc:
                self.logger.error("UTSC file deletion failed: %s", exc)
                return UtscFileDeleteResponse(success=False, error=str(exc))

        @self.router.post(
            "/files/housekeeping",
            summary="Delete aged UTSC capture files from the authoritative source",
            response_model=UtscHousekeepingResponse,
        )
        async def housekeeping_utsc_files(
            request: UtscHousekeepingRequest,
        ) -> UtscHousekeepingResponse:
            mode = _resolve_file_mode(request.vendor)
            try:
                if mode != 'agent':
                    return UtscHousekeepingResponse(**_housekeeping_pnm_files(
                        max_age_seconds=request.max_age_seconds,
                        dry_run=request.dry_run,
                        vendor=request.vendor,
                    ))

                agent_manager = get_agent_manager()
                if not agent_manager:
                    return UtscHousekeepingResponse(
                        success=False,
                        dry_run=request.dry_run,
                        error="Agent manager not available",
                    )
                agent_id = _select_file_agent(
                    agent_manager,
                    'pnm_file_housekeeping',
                    request.agent_id,
                )
                if not agent_id:
                    detail = (
                        "Requested agent does not advertise pnm_file_housekeeping"
                        if request.agent_id
                        else "No agent with pnm_file_housekeeping capability is connected"
                    )
                    return UtscHousekeepingResponse(
                        success=False,
                        dry_run=request.dry_run,
                        error=detail,
                    )

                task_id = await agent_manager.send_task(
                    agent_id=agent_id,
                    command='pnm_file_housekeeping',
                    params={
                        'max_age_seconds': request.max_age_seconds,
                        'dry_run': request.dry_run,
                    },
                    timeout=agent_manager.LONG_TASK_TIMEOUT,
                    priority='long',
                )
                result = await agent_manager.wait_for_task_async(
                    task_id,
                    timeout=agent_manager.LONG_TASK_TIMEOUT,
                )
                inner = (result or {}).get('result') or result or {}
                if inner.get('success') and not request.dry_run:
                    # In agent mode the local helper is cache-only. Do not scan
                    # or delete any local TFTP source directory.
                    _housekeeping_pnm_files(
                        max_age_seconds=request.max_age_seconds,
                        dry_run=False,
                        vendor=request.vendor,
                    )
                return UtscHousekeepingResponse(
                    success=bool(inner.get('success')),
                    dry_run=request.dry_run,
                    candidate_count=int(inner.get('candidate_count') or 0),
                    deleted_count=int(inner.get('deleted_count') or 0),
                    total_size_bytes=int(inner.get('total_size_bytes') or 0),
                    files=inner.get('files') or [],
                    errors=inner.get('errors') or [],
                    truncated=bool(inner.get('truncated', False)),
                    agent_id=agent_id,
                    error=inner.get('error'),
                )
            except Exception as exc:
                self.logger.error("UTSC housekeeping failed: %s", exc)
                return UtscHousekeepingResponse(
                    success=False,
                    dry_run=request.dry_run,
                    error=str(exc),
                )


# Required for dynamic auto-registration
router = UtscRouter().router
