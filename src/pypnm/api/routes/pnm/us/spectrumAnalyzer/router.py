from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

import asyncio
import logging
import json
import glob
import os
import struct
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

# TFTP base path for UTSC files
TFTP_BASE = "/var/lib/tftpboot"

# FTP credentials for file cleanup (TFTP dir is read-only in container)
FTP_SERVER = "127.0.0.1"
FTP_USER = "ftpaccess"
FTP_PASS = "ftpaccessftp"


def _delete_utsc_files_via_ftp(filenames: list[str]) -> int:
    """Delete UTSC files from TFTP directory via FTP."""
    if not filenames:
        return 0
    deleted = 0
    try:
        ftp = FTP()
        ftp.connect(FTP_SERVER, 21, timeout=10)
        ftp.login(FTP_USER, FTP_PASS)
        try:
            ftp.cwd('/var/lib/tftpboot')
        except Exception as e:
            logger.warning(f"FTP: Could not cd to /var/lib/tftpboot: {e}")
            ftp.quit()
            return 0
        for filename in filenames:
            try:
                ftp.delete(filename)
                deleted += 1
            except Exception:
                pass
        ftp.quit()
    except Exception as e:
        logger.error(f"FTP cleanup failed: {e}")
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
                
                # Capture parameters from GUI (no more hardcoded values)
                center_freq_hz = config.get("center_freq_hz", 37000000)
                span_hz = config.get("span_hz", 60000000)
                num_bins = config.get("num_bins", 800)
                output_format = config.get("output_format", 5)        # 5=fftAmplitude
                window = config.get("window", 4)                      # 4=blackmanHarris
                repeat_period_us = config.get("repeat_period_us", 50001)
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
    repeat_period_us: int = 50001,
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
    
    # Use params from GUI (no hardcoded values)
    actual_center_freq = center_freq_hz
    actual_span = span_hz
    actual_num_bins = num_bins
    
    logger.info(
        f"Starting spectrum stream: cmts={cmts_ip}, rfport={rf_port_ifindex}, "
        f"center={center_freq_hz}Hz, span={span_hz}Hz, bins={num_bins}, "
        f"output={output_format}, window={window}, runtime={runtime}s"
    )
    
    try:
        # Clean all old UTSC files before starting a new capture
        old_files = glob.glob(f"{TFTP_BASE}/utsc_*")
        if old_files:
            for f in old_files:
                try:
                    os.remove(f)
                except OSError:
                    pass
            logger.info(f"Cleaned {len(old_files)} old UTSC files from {TFTP_BASE}")
        
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
                # Look for UTSC files in TFTP directory
                pattern = f"{TFTP_BASE}/utsc_*"
                files = glob.glob(pattern)
                files = sorted(files, key=os.path.getmtime)  # Oldest first
                
                new_files = [f for f in files if f not in processed_files]
                
                for filepath in new_files:
                    processed_files.add(filepath)
                    try:
                        with open(filepath, 'rb') as f:
                            binary_data = f.read()
                        
                        if len(binary_data) >= 328:
                            amp_data = binary_data[328:]
                            n_samples = len(amp_data) // 2
                            
                            if n_samples > 0:
                                amplitudes = struct.unpack(f'>{n_samples}h', amp_data[:n_samples * 2])
                                bins_data = [a / 10.0 for a in amplitudes][:actual_num_bins or 1600]
                                file_buffer.append({
                                    'filepath': filepath,
                                    'bins': bins_data,
                                    'collected_at': current_time
                                })
                                logger.debug(f"Buffered {len(bins_data)} bins from {os.path.basename(filepath)} \u2014 Buffer: {len(file_buffer)}")
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
    repeat_period_us: int = 50001,
    freerun_duration_ms: int = 600000
):
    """Configure UTSC via SNMP OIDs — all parameters from GUI, nothing hardcoded."""
    from pypnm.api.agent.manager import get_agent_manager
    from pypnm.config.pnm_config_manager import PnmConfigManager
    from pypnm.config.system_config_settings import SystemConfigSettings
    
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise Exception("Agent manager not available")
    
    agent = agent_manager.get_agent_for_capability('snmp_set')
    if not agent:
        raise Exception("No agent with snmp_set capability")
    
    # Use configured write community
    write_community = os.environ.get('CMTS_WRITE_COMMUNITY') or PnmConfigManager.get_write_community() or community
    
    # UTSC Config OID base: 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1
    UTSC_CFG_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
    cfg_idx = 1  # Configuration index (always 1 on E6000)
    idx = f".{rf_port_ifindex}.{cfg_idx}"
    
    mode_name = {2: "FreeRunning", 5: "IdleSID", 6: "CM MAC"}.get(trigger_mode, f"mode {trigger_mode}")
    window_name = {2: "rectangular", 3: "hann", 4: "blackmanHarris", 5: "hamming"}.get(window, f"window {window}")
    output_name = {1: "timeIQ", 2: "fftPower", 4: "fftIQ", 5: "fftAmplitude"}.get(output_format, f"format {output_format}")
    
    # All values from GUI selections — mapped to correct SNMP OIDs
    config_steps = [
        # .2 = LogicalChIfIndex
        (f"{UTSC_CFG_BASE}.2{idx}", logical_channel_ifindex or 0, 'i', f"LogicalChIfIndex={logical_channel_ifindex or 0}"),
        # .3 = TriggerMode
        (f"{UTSC_CFG_BASE}.3{idx}", trigger_mode, 'i', f"TriggerMode={trigger_mode} ({mode_name})"),
        # .10 = NumBins
        (f"{UTSC_CFG_BASE}.10{idx}", num_bins, 'u', f"NumBins={num_bins}"),
        # .8 = CenterFreq (Hz)
        (f"{UTSC_CFG_BASE}.8{idx}", center_freq_hz, 'u', f"CenterFreq={center_freq_hz}Hz ({center_freq_hz/1e6:.1f}MHz)"),
        # .9 = Span (Hz)
        (f"{UTSC_CFG_BASE}.9{idx}", span_hz, 'u', f"Span={span_hz}Hz ({span_hz/1e6:.0f}MHz)"),
        # .17 = OutputFormat
        (f"{UTSC_CFG_BASE}.17{idx}", output_format, 'i', f"OutputFormat={output_format} ({output_name})"),
        # .16 = Window
        (f"{UTSC_CFG_BASE}.16{idx}", window, 'i', f"Window={window} ({window_name})"),
        # .19 = FreeRunDuration (ms) — SET BEFORE RepeatPeriod (must be >= RepeatPeriod raw value)
        (f"{UTSC_CFG_BASE}.19{idx}", freerun_duration_ms, 'u', f"FreeRunDuration={freerun_duration_ms}ms"),
        # .18 = RepeatPeriod (microseconds)
        (f"{UTSC_CFG_BASE}.18{idx}", repeat_period_us, 'u', f"RepeatPeriod={repeat_period_us}us ({repeat_period_us/1000:.0f}ms)"),
        # .12 = Filename
        (f"{UTSC_CFG_BASE}.12{idx}", "utsc_spectrum", 's', "Filename=utsc_spectrum"),
        # .24 = DestinationIndex (pre-configured TFTP)
        (f"{UTSC_CFG_BASE}.24{idx}", 1, 'g', "DestinationIndex=1"),
    ]
    
    for oid, value, val_type, desc in config_steps:
        logger.info(f"UTSC config: {desc}")
        try:
            task_id = await agent_manager.send_task(
                agent_id=agent.agent_id,
                command='snmp_set',
                params={
                    'target_ip': cmts_ip,
                    'oid': oid,
                    'value': value,
                    'type': val_type,
                    'community': write_community
                },
                timeout=5.0
            )
            result = await agent_manager.wait_for_task_async(task_id, timeout=10)
            if result and result.get('result', {}).get('success'):
                logger.info(f"UTSC config OK: {desc}")
            else:
                error = result.get('result', {}).get('error', 'unknown') if result else 'timeout'
                logger.error(f"UTSC config FAILED: {desc} -> {error}")
        except Exception as e:
            logger.error(f"UTSC config ERROR: {desc} -> {e}")
        await asyncio.sleep(0.1)  # Small delay between config steps
    
    logger.info(f"UTSC configured for FreeRunning mode on {cmts_ip} port {rf_port_ifindex}")


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
            community=request.cmts.community
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
