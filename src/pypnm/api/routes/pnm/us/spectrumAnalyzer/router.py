from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

import asyncio
import logging
import json
import glob
import os
from ftplib import FTP
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pypnm.api.routes.pnm.us.spectrumAnalyzer.schemas import (
    UtscRequest,
    UtscResponse,
    UtscDiscoverRequest,
    UtscDiscoverResponse,
)
from pypnm.api.routes.pnm.us.spectrumAnalyzer.service import CmtsUtscService, UtscRfPortDiscoveryService
from pypnm.config.system_config_settings import SystemConfigSettings
from pypnm.lib.inet import Inet

router = APIRouter(prefix="/pnm/us/spectrumAnalyzer", tags=["PNM - Upstream Spectrum (UTSC)"])
logger = logging.getLogger(__name__)

# Store active WebSocket connections for spectrum streaming
_spectrum_connections: list[WebSocket] = []

# Local cache dir for UTSC files fetched via FTP
_CACHE_DIR = os.environ.get('PNM_CACHE_DIR', '/app/data/pnm_cache')
TFTP_BASE = os.environ.get('TFTPBOOT_DIR', '/var/lib/tftpboot')

# FTP config from environment
FTP_SERVER = os.environ.get('FTP_SERVER_IP') or os.environ.get('TFTP_IPV4', '127.0.0.1')
FTP_USER = os.environ.get('FTP_USER', 'ftpaccess')
FTP_PASS = os.environ.get('FTP_PASSWORD', 'ftpaccessftp')
FTP_DIR = os.environ.get('FTP_TFTPBOOT_DIR', '/var/lib/tftpboot')
_USE_FTP = os.environ.get('PNM_FILE_SOURCE', 'local').lower() in ('ftp', 'agent') or os.environ.get('CMTS_TFTP', '').lower() == 'ftp'


def _resolve_cmts_tftp_mode(vendor: str = '') -> str:
    """Resolve retrieval mode for a CMTS vendor.

    Supported values: ftp | agent | local
    Vendor env aliases:
      - CISCO_TFTP
      - COMMSCOPE_TFTP
      - CASA_TFTP
    If vendor key is not set, falls back to CMTS_TFTP.
    """
    vendor_lc = (vendor or '').strip().lower()

    vendor_values: list[str] = []
    if 'cisco' in vendor_lc or 'cbr' in vendor_lc:
        vendor_values = [
            os.environ.get('CISCO_TFTP', ''),
            os.environ.get('CMTS_TFTP_CISCO', ''),
            os.environ.get('PNM_FILE_SOURCE_CMTS_CISCO', ''),
        ]
    elif 'arris' in vendor_lc or 'commscope' in vendor_lc or 'e6000' in vendor_lc:
        vendor_values = [
            os.environ.get('COMMSCOPE_TFTP', ''),
            os.environ.get('CMTS_TFTP_COMMSCOPE', ''),
            os.environ.get('PNM_FILE_SOURCE_CMTS_COMMSCOPE', ''),
        ]
    elif 'casa' in vendor_lc or 'evo' in vendor_lc or 'vccap' in vendor_lc:
        vendor_values = [
            os.environ.get('CASA_TFTP', ''),
            os.environ.get('CMTS_TFTP_CASA', ''),
            os.environ.get('PNM_FILE_SOURCE_CMTS_CASA', ''),
        ]

    for raw in vendor_values:
        mode = (raw or '').strip().lower()
        if mode in ('ftp', 'agent', 'local'):
            return mode

    fallback = (
        os.environ.get('CMTS_TFTP', '')
        or os.environ.get('PNM_FILE_SOURCE_CMTS', '')
        or os.environ.get('PNM_FILE_SOURCE', 'local')
    ).strip().lower()
    return fallback if fallback in ('ftp', 'agent', 'local') else 'local'


def _mode_uses_ftp(mode: str) -> bool:
    return (mode or '').strip().lower() == 'ftp'


def _get_utsc_base() -> str:
    """Return the primary directory to read UTSC files from.

    Agent-fetched files land in _CACHE_DIR.  Local TFTP mount is TFTP_BASE.
    Returns _CACHE_DIR (always exists) so agent-fetched files are found.
    The streaming loop also searches TFTP_BASE for locally-mounted files.
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return _CACHE_DIR


def _ftp_fetch_utsc_files(mode: str = '') -> list[str]:
    """Fetch all UTSC files from FTP server into local cache. Returns list of local paths."""
    if not _mode_uses_ftp(mode):
        return []
    os.makedirs(_CACHE_DIR, exist_ok=True)
    fetched = []
    try:
        ftp = FTP()
        ftp.connect(FTP_SERVER, 21, timeout=10)
        ftp.login(FTP_USER, FTP_PASS)
        try:
            ftp.cwd(FTP_DIR)
        except Exception as e:
            logger.warning(f"FTP: Could not cd to {FTP_DIR}: {e}")
            ftp.quit()
            return []
        try:
            all_files = ftp.nlst()
        except Exception:
            all_files = []
        matching = [f for f in all_files if os.path.basename(f).startswith('utsc_') or os.path.basename(f).startswith('PNMCcapUsSpecAn_')]
        for remote_file in matching:
            basename = os.path.basename(remote_file)
            local_path = os.path.join(_CACHE_DIR, basename)
            if not os.path.exists(local_path):
                try:
                    with open(local_path, 'wb') as fp:
                        ftp.retrbinary(f'RETR {basename}', fp.write)
                    fetched.append(local_path)
                except Exception as e:
                    logger.debug(f"FTP fetch {basename} failed: {e}")
        ftp.quit()
    except Exception as e:
        logger.debug(f"FTP fetch error: {e}")
    return fetched


async def _agent_fetch_utsc_files(processed_files: set[str], mode: str = '') -> list[str]:
    """Fetch new UTSC files via file-agent WebSocket (bypasses FTP overhead).

    Two-step approach:
    1. ``file_list`` — ask the agent for all filenames matching UTSC prefixes
       (fast: no file content transferred)
    2. ``file_get`` — fetch only the files not yet processed (returns base64)

    Falls back to FTP when mode is ftp and no file-agent is available.
    """
    import base64
    from pypnm.api.agent.manager import get_agent_manager

    agent_manager = get_agent_manager()
    if not agent_manager:
        return _ftp_fetch_utsc_files(mode)

    file_list_ids = agent_manager.get_all_agent_ids_for_capability('file_list')
    pnm_file_ids = agent_manager.get_all_agent_ids_for_capability('pnm_file_get')

    # Prefer agents explicitly advertising pnm_file_get, then fall back to generic file_list.
    candidate_ids: list[str] = [aid for aid in file_list_ids if aid in pnm_file_ids]
    candidate_ids.extend([aid for aid in file_list_ids if aid not in candidate_ids])
    candidate_ids.extend([aid for aid in pnm_file_ids if aid not in candidate_ids])

    if not candidate_ids:
        return _ftp_fetch_utsc_files(mode)
    os.makedirs(_CACHE_DIR, exist_ok=True)

    # Step 1: list matching files on candidate agents' TFTP roots.
    # Try multiple candidates to avoid selecting a connected agent with no file access.
    remote_files: list[str] = []
    agent_id: str | None = None
    had_list_success = False
    for candidate_id in candidate_ids:
        try:
            task_id = await agent_manager.send_task(
                agent_id=candidate_id,
                command='file_list',
                params={'prefixes': ['utsc_', 'PNMCcapUsSpecAn_']},
                timeout=10,
            )
            result = await agent_manager.wait_for_task_async(task_id, timeout=10)
            result_inner = (result or {}).get('result') or result or {}
            if not result_inner.get('success'):
                continue
            had_list_success = True

            files = result_inner.get('files', []) or []
            if files:
                agent_id = candidate_id
                remote_files = files
                break
        except Exception as e:
            logger.debug(f"Agent file_list failed for {candidate_id}: {e}")

    if agent_id is None:
        # Hybrid mode: some CMTS types still land files on FTP/TFTP paths.
        # If agent listing had no matches, also try FTP fetch when enabled.
        if _mode_uses_ftp(mode):
            return _ftp_fetch_utsc_files(mode)
        return []

    # Filter to only files we haven't processed yet
    processed_basenames = {os.path.basename(p) for p in processed_files}
    new_files = [f for f in remote_files
                 if f not in processed_basenames
                 and not os.path.exists(os.path.join(_CACHE_DIR, f))]

    if not new_files:
        return []

    # Step 2: fetch each new file via file_get
    fetched: list[str] = []
    for filename in new_files:
        try:
            task_id = await agent_manager.send_task(
                agent_id=agent_id,
                command='file_get',
                params={'filename': filename, 'glob': False},
                timeout=15,
                priority='bulk',
            )
            result = await agent_manager.wait_for_task_async(task_id, timeout=15)
            result_inner = (result or {}).get('result') or result or {}
            if not result_inner.get('success'):
                continue

            content = base64.b64decode(result_inner['content_base64'])
            local_path = os.path.join(_CACHE_DIR, filename)
            with open(local_path, 'wb') as fh:
                fh.write(content)
            fetched.append(local_path)
            logger.debug(f"Agent fetched UTSC file: {filename} ({len(content)} bytes)")
        except Exception as e:
            logger.debug(f"Agent file_get failed for {filename}: {e}")

    if fetched:
        logger.info(f"Agent fetched {len(fetched)} new UTSC file(s)")
    return fetched


def _delete_utsc_files_via_ftp(filenames: list[str], mode: str = '') -> int:
    """Delete UTSC files from FTP server and local cache."""
    if not filenames:
        return 0
    deleted = 0
    # Delete from local cache
    base = _get_utsc_base()
    for fn in filenames:
        local = os.path.join(base, os.path.basename(fn))
        try:
            if os.path.exists(local):
                os.remove(local)
                deleted += 1
        except OSError:
            pass
    # Delete from FTP server
    if _mode_uses_ftp(mode):
        try:
            ftp = FTP()
            ftp.connect(FTP_SERVER, 21, timeout=10)
            ftp.login(FTP_USER, FTP_PASS)
            try:
                ftp.cwd(FTP_DIR)
            except Exception as e:
                logger.warning(f"FTP: Could not cd to {FTP_DIR}: {e}")
                ftp.quit()
                return deleted
            for filename in filenames:
                try:
                    ftp.delete(os.path.basename(filename))
                except Exception:
                    pass
            ftp.quit()
        except Exception as e:
            logger.debug(f"FTP cleanup failed: {e}")
    return deleted


@router.websocket("/stream")
async def spectrum_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time spectrum data streaming.
    
    Clients connect here to receive spectrum updates as they become available.
    Protocol:
    - Client sends JSON: {"cmts_ip": "...", "rf_port_ifindex": ..., "community": "...", "trigger_mode": 1}
    - Server sends spectrum data frames: {"freq_start_hz": ..., "freq_step_hz": ..., "bins": [...]}
    """
    await websocket.accept()
    _spectrum_connections.append(websocket)
    logger.info(f"Spectrum WebSocket client connected. Total: {len(_spectrum_connections)}")
    
    try:
        while True:
            # Receive configuration from client
            data = await websocket.receive_text()
            try:
                config = json.loads(data)
                cmts_ip = config.get("cmts_ip")
                rf_port_ifindex = config.get("rf_port_ifindex")
                logical_channel_ifindex = config.get("logical_channel_ifindex")  # Optional SC-QAM channel
                community = config.get("community", "private")
                interval_ms = config.get("interval_ms", 500)
                trigger_mode = config.get("trigger_mode", 2)  # Default to FreeRunning (2)
                skip_configure = config.get("skip_configure", False)  # Skip if already configured via REST
                
                center_freq_hz = config.get("center_freq_hz", 37000000)
                span_hz = config.get("span_hz", 60000000)
                num_bins = config.get("num_bins", 800)
                output_format = config.get("output_format", 5)        # 5=fftAmplitude
                window = config.get("window", 4)                      # 4=blackmanHarris
                repeat_period_us = config.get("repeat_period_us", 100000)
                freerun_duration_ms = config.get("freerun_duration_ms", 600000)
                runtime = config.get("runtime", 60)  # seconds - total streaming runtime
                
                if not cmts_ip or not rf_port_ifindex:
                    await websocket.send_json({"error": "cmts_ip and rf_port_ifindex required"})
                    continue
                
                # Start streaming spectrum data
                await _stream_spectrum_data(
                    websocket, cmts_ip, rf_port_ifindex, community, interval_ms, trigger_mode,
                    logical_channel_ifindex, skip_configure,
                    center_freq_hz=center_freq_hz,
                    span_hz=span_hz,
                    num_bins=num_bins,
                    output_format=output_format,
                    window=window,
                    repeat_period_us=repeat_period_us,
                    freerun_duration_ms=freerun_duration_ms,
                    runtime=runtime
                )
                
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                
    except WebSocketDisconnect:
        logger.info("Spectrum WebSocket client disconnected")
    finally:
        if websocket in _spectrum_connections:
            _spectrum_connections.remove(websocket)


@router.websocket("/stream/fake")
async def spectrum_stream_fake(websocket: WebSocket):
    """
    Fake spectrum data stream for debugging the spectrum analyzer UI.
    Generates realistic upstream return path spectrum with:
    - Noise floor around -50 dBmV
    - SC-QAM carriers at known DOCSIS upstream frequencies
    - Random noise variation
    - Optional ingress burst simulation
    """
    import random
    import math
    import time

    await websocket.accept()
    logger.info("Fake spectrum WebSocket connected")

    # Upstream return path: 5-85 MHz
    center_freq_hz = 45_000_000   # 45 MHz center
    span_hz = 80_000_000          # 80 MHz span (5-85 MHz)
    num_bins = 1600
    freq_start_hz = center_freq_hz - span_hz // 2  # 5 MHz
    freq_step_hz = span_hz / num_bins               # 50 kHz per bin

    # SC-QAM upstream carriers (typical DOCSIS 3.0 upstream channels)
    carriers = [
        {"freq": 10_400_000, "bw": 6_400_000, "level": -25.0},  # US ch 1
        {"freq": 17_000_000, "bw": 6_400_000, "level": -24.0},  # US ch 2
        {"freq": 23_400_000, "bw": 6_400_000, "level": -26.0},  # US ch 3
        {"freq": 30_000_000, "bw": 6_400_000, "level": -25.5},  # US ch 4
        {"freq": 36_800_000, "bw": 6_400_000, "level": -24.5},  # OFDMA pilot
    ]

    frame = 0
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Fake spectrum stream - debug mode"
        })

        while True:
            frame += 1
            t = time.time()
            bins = []

            for i in range(num_bins):
                freq = freq_start_hz + i * freq_step_hz
                # Base noise floor with slight frequency-dependent slope
                val = -50.0 + (freq / 100_000_000) * 3.0  # slight upward slope

                # Add carriers
                for c in carriers:
                    half_bw = c["bw"] / 2
                    if abs(freq - c["freq"]) < half_bw:
                        # Raised cosine shape
                        x = abs(freq - c["freq"]) / half_bw
                        shape = 0.5 * (1 + math.cos(math.pi * x))
                        val = max(val, c["level"] + 2.0 * shape)

                # Random noise
                val += random.gauss(0, 0.8)

                # Simulated ingress burst at ~7 MHz every 5 seconds for 1 second
                if 6_000_000 < freq < 8_000_000:
                    phase = t % 5.0
                    if phase < 1.0:
                        ingress_level = -30.0 + 10.0 * math.sin(math.pi * phase)
                        val = max(val, ingress_level + random.gauss(0, 1.5))

                bins.append(round(val, 1))

            await websocket.send_json({
                "freq_start_hz": freq_start_hz,
                "freq_step_hz": freq_step_hz,
                "bins": bins,
                "buffer_size": 0
            })

            await asyncio.sleep(0.5)  # 2 fps

    except WebSocketDisconnect:
        logger.info("Fake spectrum WebSocket disconnected")
    except Exception as e:
        logger.error(f"Fake spectrum error: {e}")


async def _poll_utsc_status(cmts_ip: str, rf_port_ifindex: int, community: str) -> int | None:
    """Poll UTSC MeasStatus via SNMP GET. Returns integer status or None."""
    from pypnm.api.agent.manager import get_agent_manager
    from pypnm.config.pnm_config_manager import PnmConfigManager
    
    agent_manager = get_agent_manager()
    if not agent_manager:
        return None
    agent = agent_manager.get_agent_for_capability('snmp_get')
    if not agent:
        return None
    
    write_community = os.environ.get('CMTS_WRITE_COMMUNITY') or PnmConfigManager.get_write_community() or community
    oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1.{rf_port_ifindex}.1"
    
    if not hasattr(_poll_utsc_status, '_logged_raw'):
        _poll_utsc_status._logged_raw = False
    
    try:
        task_id = await agent_manager.send_task(
            agent_id=agent.agent_id,
            command='snmp_get',
            params={
                'target_ip': cmts_ip,
                'oid': oid,
                'community': write_community,
                'timeout': 5
            },
            timeout=10.0
        )
        result = await agent_manager.wait_for_task_async(task_id, timeout=10)
        if not _poll_utsc_status._logged_raw:
            logger.info(f"UTSC status raw result (once): {result}")
            _poll_utsc_status._logged_raw = True
        if result and result.get('result', {}).get('success'):
            results_list = result['result'].get('results', [])
            if results_list:
                val = results_list[0].get('value', '')
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
            # Try parsing output string
            output = result['result'].get('output', '')
            if 'INTEGER:' in output:
                try:
                    return int(output.split('INTEGER:')[1].strip().split('(')[0].strip())
                except (ValueError, IndexError):
                    pass
        else:
            logger.warning(f"UTSC status poll failed or no success flag: {result}")
    except Exception as e:
        logger.error(f"UTSC status poll exception: {e}")
    return None


async def _stream_spectrum_data(
    websocket: WebSocket,
    cmts_ip: str,
    rf_port_ifindex: int,
    community: str,
    interval_ms: int,
    trigger_mode: int = 2,
    logical_channel_ifindex: int = None,
    skip_configure: bool = False,
    center_freq_hz: int = 37000000,
    span_hz: int = 60000000,
    num_bins: int = 800,
    output_format: int = 5,
    window: int = 4,
    repeat_period_us: int = 100000,
    freerun_duration_ms: int = 600000,
    runtime: int = 60
):
    """Stream spectrum data to WebSocket client by reading TFTP files.
    
    E6000 FreeRunning behaviour (empirically confirmed 14-Feb-2026):
    - Produces exactly 10 files per trigger in a ~200ms burst, then status -> sampleReady
    - FreeRunDuration / RepeatPeriod do NOT make it produce more than 10 files
    - To get continuous data: wait 30s for initial buffer, then re-trigger as soon
      as sampleReady(4) appears in the MIB
    - All capture parameters (center freq, span, bins, window, output format) are
      configured via SNMP OIDs from the GUI selections
    """
    from collections import deque
    import time
    
    # Track processed files by name
    processed_files = set()
    
    # Buffer for smooth playback
    file_buffer = deque(maxlen=500)
    initial_buffer_target = 2        # Start streaming once we have 2 samples
    initial_buffer_wait_s = 3        # Wait just 3s before checking buffer
    streaming_started = False
    
    # Re-trigger tracking
    run_counter = 0
    retrigger_count = 0
    last_trigger_time = 0            # When we last fired SNMP trigger
    poll_window_start_s = 25         # Start polling sampleReady at 25s after trigger
    poll_window_end_s = 31           # Stop polling at 31s
    fallback_retrigger_s = 35        # Fallback retrigger if poll didn't find sampleReady
    
    # Stream timing — pace frames to make buffer last
    stream_interval = max(interval_ms / 1000.0, 2.0)  # Min 2s between sends to pace buffer
    last_stream_time = 0
    last_heartbeat = 0
    
    # Real-time mode: skip frames if buffer gets too large
    max_buffer_for_realtime = 100
    
    # Cleanup tracking
    files_to_delete = []
    cleanup_batch_size = 50

    actual_center_freq = center_freq_hz
    actual_span = span_hz
    actual_num_bins = num_bins
    
    logger.info(
        f"Starting spectrum stream: cmts={cmts_ip}, rfport={rf_port_ifindex}, "
        f"center={center_freq_hz}Hz, span={span_hz}Hz, bins={num_bins}, "
        f"output={output_format}, window={window}, runtime={runtime}s"
    )

    # Resolve retrieval mode from env only — no live SNMP probe needed.
    # To override per vendor set CISCO_TFTP=, COMMSCOPE_TFTP=, or CASA_TFTP=
    # in the environment.  Fallback: CMTS_TFTP -> PNM_FILE_SOURCE.
    stream_mode = _resolve_cmts_tftp_mode('')
    logger.info(f"UTSC stream retrieval mode={stream_mode}")
    
    try:
        # Clean all old UTSC files before starting a new capture
        utsc_base = _get_utsc_base()
        old_files = glob.glob(f"{utsc_base}/utsc_*") + glob.glob(f"{utsc_base}/PNMCcapUsSpecAn_*")
        if old_files:
            _delete_utsc_files_via_ftp([os.path.basename(f) for f in old_files], mode=stream_mode)
            logger.info(f"Cleaned {len(old_files)} old UTSC files")
        
        await websocket.send_json({
            "type": "connected",
            "message": f"UTSC stream connected — configuring and starting capture..."
        })
        
        # Configure and trigger UTSC with parameters from the GUI
        if cmts_ip and rf_port_ifindex and not skip_configure:
            logger.info(f"Configuring UTSC on {cmts_ip} port {rf_port_ifindex}")
            try:
                await _configure_utsc(
                    cmts_ip, rf_port_ifindex, community,
                    trigger_mode=trigger_mode,
                    center_freq_hz=center_freq_hz,
                    span_hz=span_hz,
                    num_bins=num_bins,
                    output_format=output_format,
                    window=window,
                    repeat_period_us=repeat_period_us,
                    freerun_duration_ms=freerun_duration_ms,
                    logical_channel_ifindex=logical_channel_ifindex
                )
                await _trigger_utsc(cmts_ip, rf_port_ifindex, community)
                run_counter += 1
                last_trigger_time = time.time()
            except Exception as e:
                logger.error(f"UTSC config/trigger failed: {e}")
        elif skip_configure:
            logger.info(f"Skipping UTSC config (already configured via REST)")
            run_counter = 1
            last_trigger_time = time.time()
        
        buffer_start_time = time.time()
        stream_start_time = None  # Set when streaming actually starts
        
        while True:
            current_time = time.time()
            
            # Check runtime limit (counted from when streaming starts, not buffer phase)
            if stream_start_time and (current_time - stream_start_time) >= runtime:
                await websocket.send_json({
                    "type": "complete",
                    "message": f"Runtime complete ({runtime}s). {retrigger_count} re-triggers.",
                    "total_triggers": retrigger_count,
                    "runtime_s": runtime
                })
                logger.info(f"Spectrum stream runtime complete ({runtime}s)")
                break
            
            try:
                # Fetch files via agent (WebSocket) or FTP depending on mode,
                # then discover local files from both cache and local TFTP mount.
                if stream_mode == 'agent':
                    await _agent_fetch_utsc_files(processed_files, mode=stream_mode)
                elif _mode_uses_ftp(stream_mode):
                    _ftp_fetch_utsc_files(stream_mode)
                # local mode: files arrive directly on TFTP_BASE — discovered below
                roots = []
                for root in (_get_utsc_base(), TFTP_BASE):
                    if root and root not in roots and os.path.isdir(root):
                        roots.append(root)
                all_files = []
                for root in roots:
                    all_files.extend(glob.glob(f"{root}/utsc_*"))
                    all_files.extend(glob.glob(f"{root}/PNMCcapUsSpecAn_*"))
                files = sorted(set(all_files), key=os.path.getmtime)  # Oldest first
                
                new_files = [f for f in files if f not in processed_files]
                
                for filepath in new_files:
                    processed_files.add(filepath)
                    try:
                        with open(filepath, 'rb') as f:
                            binary_data = f.read()
                        
                        from pypnm.pnm.parser.utsc_file import parse_utsc_file

                        sample = parse_utsc_file(
                            binary_data,
                            filename=os.path.basename(filepath),
                            vendor='cisco' if 'PNMCcap' in os.path.basename(filepath) else 'commscope',
                            center_freq_hz=actual_center_freq,
                            span_hz=actual_span,
                            max_bins=actual_num_bins or 1600,
                        )
                        file_buffer.append({
                            'filepath': filepath,
                            'bins': sample['bins'],
                            'collected_at': current_time,
                        })
                        logger.debug(
                            "Buffered %s bins from %s — Buffer: %s",
                            len(sample['bins']), os.path.basename(filepath), len(file_buffer),
                        )
                    except Exception as e:
                        logger.error(f"Error parsing {filepath}: {e}")
                
                # === Re-trigger logic ===
                # E6000 produces ~10 files per trigger burst then stops.
                # Poll sampleReady(4) between 25-31s after trigger, fallback at 35s.
                if run_counter > 0 and last_trigger_time > 0:
                    seconds_since_trigger = current_time - last_trigger_time
                    
                    # Window 25-31s: poll SNMP for sampleReady
                    if poll_window_start_s <= seconds_since_trigger <= poll_window_end_s:
                        try:
                            status_val = await _poll_utsc_status(cmts_ip, rf_port_ifindex, community)
                            if status_val == 4:
                                logger.info(f"sampleReady detected at {seconds_since_trigger:.0f}s, re-triggering UTSC...")
                                await _trigger_utsc(cmts_ip, rf_port_ifindex, community)
                                retrigger_count += 1
                                run_counter += 1
                                last_trigger_time = current_time
                                logger.info(f"Re-triggered UTSC #{retrigger_count}")
                            else:
                                logger.debug(f"UTSC status at {seconds_since_trigger:.0f}s: {status_val}")
                        except Exception as e:
                            logger.debug(f"Status poll error: {e}")
                    
                    # Fallback at 35s: retrigger anyway if sampleReady was never detected
                    elif seconds_since_trigger >= fallback_retrigger_s:
                        try:
                            logger.info(f"Fallback retrigger at {seconds_since_trigger:.0f}s (sampleReady not detected in window)")
                            await _trigger_utsc(cmts_ip, rf_port_ifindex, community)
                            retrigger_count += 1
                            run_counter += 1
                            last_trigger_time = current_time
                            logger.info(f"Re-triggered UTSC #{retrigger_count} (fallback)")
                        except Exception as e:
                            logger.error(f"Fallback re-trigger failed: {e}")
                
                # === 30-second buffer phase ===
                if not streaming_started:
                    elapsed_buffer = current_time - buffer_start_time
                    
                    if elapsed_buffer >= initial_buffer_wait_s and len(file_buffer) >= initial_buffer_target:
                        streaming_started = True
                        stream_start_time = current_time
                        logger.info(f"Buffer ready: {len(file_buffer)} samples after {elapsed_buffer:.0f}s. Starting stream (runtime={runtime}s)")
                        await websocket.send_json({
                            "type": "buffering_complete",
                            "message": f"Buffered {len(file_buffer)} samples in {elapsed_buffer:.0f}s. Streaming for {runtime}s...",
                            "buffer_size": len(file_buffer)
                        })
                    elif elapsed_buffer >= initial_buffer_wait_s and len(file_buffer) < initial_buffer_target:
                        # Been waiting 30s but not enough data - start anyway if we have anything
                        if len(file_buffer) > 0:
                            streaming_started = True
                            stream_start_time = current_time
                            logger.warning(f"Buffer timeout: only {len(file_buffer)} samples after {elapsed_buffer:.0f}s. Starting stream anyway.")
                            await websocket.send_json({
                                "type": "buffering_complete",
                                "message": f"Buffer partial ({len(file_buffer)} samples). Streaming...",
                                "buffer_size": len(file_buffer)
                            })
                    else:
                        # Still buffering - send progress updates
                        if current_time - last_heartbeat > 2:
                            remaining = max(0, initial_buffer_wait_s - elapsed_buffer)
                            await websocket.send_json({
                                "type": "buffering",
                                "message": f"Please wait \u2014 building buffer... {len(file_buffer)} samples, {remaining:.0f}s remaining",
                                "buffer_size": len(file_buffer),
                                "target": initial_buffer_target,
                                "wait_remaining_s": round(remaining, 1)
                            })
                            last_heartbeat = current_time
                
                # Stream from buffer at controlled rate
                if streaming_started and file_buffer and (current_time - last_stream_time) >= stream_interval:
                    if len(file_buffer) > max_buffer_for_realtime:
                        skip_count = len(file_buffer) - 10
                        for _ in range(skip_count):
                            old = file_buffer.popleft()
                            files_to_delete.append(os.path.basename(old['filepath']))
                        logger.debug(f"Skipped {skip_count} frames to stay real-time")
                    
                    item = file_buffer.popleft()
                    files_to_delete.append(os.path.basename(item['filepath']))
                    last_stream_time = current_time
                    
                    bins_out = item['bins']
                    actual_bins = len(bins_out)
                    freq_start_hz = actual_center_freq - (actual_span // 2)
                    freq_step_hz = actual_span // actual_bins if actual_bins > 0 else 100000
                    
                    stream_elapsed = current_time - stream_start_time if stream_start_time else 0
                    
                    await websocket.send_json({
                        "freq_start_hz": freq_start_hz,
                        "freq_step_hz": freq_step_hz,
                        "bins": bins_out,
                        "buffer_size": len(file_buffer),
                        "runtime_elapsed_s": round(stream_elapsed, 1),
                        "runtime_total_s": runtime,
                        "triggers": retrigger_count
                    })
                    logger.info(f"Streamed {actual_bins} bins, buffer: {len(file_buffer)}, elapsed: {stream_elapsed:.0f}s/{runtime}s")
                
                # Batch FTP cleanup
                if len(files_to_delete) >= cleanup_batch_size:
                    deleted = _delete_utsc_files_via_ftp(files_to_delete)
                    logger.debug(f"FTP cleanup: deleted {deleted}/{len(files_to_delete)} files")
                    files_to_delete = []
                
                # Heartbeat
                if current_time - last_heartbeat > 5:
                    stream_elapsed = current_time - stream_start_time if stream_start_time else 0
                    await websocket.send_json({
                        "type": "heartbeat",
                        "buffer_size": len(file_buffer),
                        "runs": run_counter,
                        "triggers": retrigger_count,
                        "runtime_elapsed_s": round(stream_elapsed, 1) if stream_start_time else 0
                    })
                    last_heartbeat = current_time
                
            except Exception as e:
                logger.debug(f"Spectrum fetch error: {e}")
            
            await asyncio.sleep(0.05)  # 50ms polling
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected after {retrigger_count} re-triggers")
    finally:
        # Stop capture on CMTS
        try:
            await _abort_utsc(cmts_ip, rf_port_ifindex, community)
        except Exception:
            pass
        # Final FTP cleanup
        if files_to_delete:
            _delete_utsc_files_via_ftp(files_to_delete)


async def _configure_utsc(
    cmts_ip: str,
    rf_port_ifindex: int,
    community: str,
    trigger_mode: int = 2,
    logical_channel_ifindex: int = None,
    center_freq_hz: int = 37000000,
    span_hz: int = 60000000,
    num_bins: int = 800,
    output_format: int = 5,
    window: int = 4,
    repeat_period_us: int = 100000,
    freerun_duration_ms: int = 600000
):
    """Configure UTSC using destroy → createAndWait → set columns → activate.

    This sequence works on all CMTS vendors (E6000, Casa, Cisco).
    Setting TriggerMode on an already-active row is rejected by some vendors,
    so we always destroy and recreate to guarantee a clean slate.
    """
    from pypnm.config.pnm_config_manager import PnmConfigManager
    from pypnm.api.routes.pnm.us.spectrumAnalyzer.service import CmtsUtscService

    write_community = os.environ.get('CMTS_WRITE_COMMUNITY') or PnmConfigManager.get_write_community() or community

    svc = CmtsUtscService(
        cmts_ip=cmts_ip,
        rf_port_ifindex=rf_port_ifindex,
        community=community,
        write_community=write_community
    )
    result = await svc.configure_row(
        center_freq_hz=center_freq_hz,
        span_hz=span_hz,
        num_bins=num_bins,
        trigger_mode=trigger_mode,
        filename="utsc_spectrum",
        logical_ch_ifindex=logical_channel_ifindex,
        repeat_period_ms=max(50, repeat_period_us // 1000),
        freerun_duration_ms=freerun_duration_ms,
        output_format=output_format,
        window=window
    )
    if not result.get("success"):
        raise Exception(f"UTSC configure failed: {result.get('error')}")
    logger.info(f"UTSC configured on {cmts_ip} port {rf_port_ifindex} — trigger_mode={trigger_mode}")


async def _trigger_utsc(cmts_ip: str, rf_port_ifindex: int, community: str):
    """Trigger UTSC capture via SNMP set through agent (fire-and-forget)."""
    from pypnm.api.agent.manager import get_agent_manager
    from pypnm.config.pnm_config_manager import PnmConfigManager
    
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise Exception("Agent manager not available")
    
    # Find agent with snmp_set capability
    agent = agent_manager.get_agent_for_capability('snmp_set')
    if not agent:
        raise Exception("No agent with snmp_set capability")
    
    # Use configured write community from env or config
    write_community = os.environ.get('CMTS_WRITE_COMMUNITY') or PnmConfigManager.get_write_community() or community
    
    # OID for UTSC control: docsPnmCmtsUtscCtrlCmd
    oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{rf_port_ifindex}.1"
    
    # Fire and forget - don't wait for response, SNMP set is slow
    task_id = await agent_manager.send_task(
        agent_id=agent.agent_id,
        command='snmp_set',
        params={
            'target_ip': cmts_ip,
            'oid': oid,
            'value': 1,  # 1 = start
            'type': 'i',
            'community': write_community
        },
        timeout=10.0
    )
    
    logger.info(f"UTSC trigger sent to {cmts_ip} port {rf_port_ifindex} (task {task_id})")


async def _abort_utsc(cmts_ip: str, rf_port_ifindex: int, community: str):
    """Abort/reset UTSC capture via SNMP set through agent."""
    from pypnm.api.agent.manager import get_agent_manager
    from pypnm.config.pnm_config_manager import PnmConfigManager
    
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise Exception("Agent manager not available")
    
    agent = agent_manager.get_agent_for_capability('snmp_set')
    if not agent:
        raise Exception("No agent with snmp_set capability")
    
    write_community = os.environ.get('CMTS_WRITE_COMMUNITY') or PnmConfigManager.get_write_community() or community
    
    # OID for UTSC control: docsPnmCmtsUtscCtrlCmd - value 2 = abort
    oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{rf_port_ifindex}.1"
    
    task_id = await agent_manager.send_task(
        agent_id=agent.agent_id,
        command='snmp_set',
        params={
            'target_ip': cmts_ip,
            'oid': oid,
            'value': 2,  # 2 = abort
            'type': 'i',
            'community': write_community
        },
        timeout=5.0
    )
    
    logger.info(f"UTSC abort sent to {cmts_ip} port {rf_port_ifindex} (task {task_id})")


@router.post("/getCapture", response_model=UtscResponse)
async def get_utsc_capture(request: UtscRequest) -> UtscResponse:
    """
    Perform Upstream Triggered Spectrum Capture (UTSC) on CMTS.
    
    UTSC is CMTS-based, not modem-based. Sends SNMP to CMTS using RF port ifIndex.
    Supports FreeRunning and CM MAC Address trigger modes.
    """
    logger.info(f"UTSC: CMTS={request.cmts.cmts_ip}, RF Port={request.cmts.rf_port_ifindex}")
    
    try:
        # Get TFTP IP from request or fall back to system config
        tftp_ip = request.tftp.ipv4 if request.tftp.ipv4 else SystemConfigSettings.bulk_tftp_ip_v4()
        if not tftp_ip:
            return UtscResponse(success=False, error="TFTP IPv4 address required but not provided in request or system config")
        
        service = CmtsUtscService(
            cmts_ip=Inet(request.cmts.cmts_ip),
            rf_port_ifindex=request.cmts.rf_port_ifindex,
            community=request.cmts.community,
            write_community=getattr(request.cmts, 'write_community', None)
        )
        
        # Step 1: Reset port to clean state (stop any active capture, wait for ready)
        reset_result = await asyncio.wait_for(
            service.reset_port_state(),
            timeout=15.0
        )
        if not reset_result.get("success"):
            logger.warning(f"Port reset warning: {reset_result.get('error')}")
            # Continue anyway - the port might still be usable
        
        # Step 2: Configure UTSC with 60 second timeout
        result = await asyncio.wait_for(
            service.configure(
                center_freq_hz=request.capture_parameters.center_freq_hz,
                span_hz=request.capture_parameters.span_hz,
                num_bins=request.capture_parameters.num_bins,
                trigger_mode=request.capture_parameters.trigger_mode,
                filename=request.capture_parameters.filename,
                tftp_ip=str(tftp_ip),
                cm_mac=request.trigger.cm_mac,
                logical_ch_ifindex=request.trigger.logical_ch_ifindex,
                repeat_period_ms=request.capture_parameters.repeat_period_ms,
                freerun_duration_ms=request.capture_parameters.freerun_duration_ms,
                trigger_count=request.capture_parameters.trigger_count,
                output_format=request.capture_parameters.output_format,
                window=request.capture_parameters.window
            ),
            timeout=60.0
        )
        
        if not result.get("success"):
            logger.error(f"UTSC configuration failed: {result.get('error')}")
            return UtscResponse(success=False, error=result.get("error"))
        
        # Start capture with 15 second timeout
        start_result = await asyncio.wait_for(
            service.start(),
            timeout=15.0
        )
        
        if not start_result.get("success"):
            logger.error(f"UTSC start failed: {start_result.get('error')}")
            return UtscResponse(success=False, error=start_result.get("error"))
        
        logger.info("UTSC capture completed successfully")
        return UtscResponse(
            success=True,
            cmts_ip=str(request.cmts.cmts_ip),
            rf_port_ifindex=request.cmts.rf_port_ifindex,
            filename=request.capture_parameters.filename,
            data={"message": "UTSC started", "tftp_path": "./"}
        )
        
    except asyncio.TimeoutError:
        error_msg = "UTSC operation timed out after 75 seconds"
        logger.error(error_msg)
        return UtscResponse(success=False, error=error_msg)
    except Exception as e:
        error_msg = f"UTSC operation failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return UtscResponse(success=False, error=error_msg)


@router.post("/discoverRfPort", response_model=UtscDiscoverResponse)
async def discover_rf_port(request: UtscDiscoverRequest) -> UtscDiscoverResponse:
    """
    Discover the correct UTSC RF port for a cable modem.
    
    Uses the modem's upstream logical channel to find which RF port it belongs to.
    This is much faster than manual discovery as it tests the logical channel
    against each RF port until it finds a match.
    """
    logger.info(f"UTSC RF Port Discovery: CMTS={request.cmts_ip}, MAC={request.cm_mac_address}")
    
    try:
        service = UtscRfPortDiscoveryService(
            cmts_ip=request.cmts_ip,
            community=request.community
        )
        
        result = await asyncio.wait_for(
            service.discover(request.cm_mac_address),
            timeout=60.0
        )
        
        return UtscDiscoverResponse(
            success=result.get("success", False),
            rf_port_ifindex=result.get("rf_port_ifindex"),
            rf_port_description=result.get("rf_port_description"),
            cm_index=result.get("cm_index"),
            us_channels=result.get("us_channels", []),
            error=result.get("error")
        )
        
    except asyncio.TimeoutError:
        error_msg = "RF port discovery timed out"
        logger.error(error_msg)
        return UtscDiscoverResponse(success=False, error=error_msg)
    except Exception as e:
        error_msg = f"RF port discovery failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return UtscDiscoverResponse(success=False, error=error_msg)
