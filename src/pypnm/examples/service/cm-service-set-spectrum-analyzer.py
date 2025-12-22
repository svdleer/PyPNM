#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import argparse
import asyncio
import logging

from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.extended.common_process_service import CommonProcessService
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.schemas import SpecAnCapturePara
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.service import CmSpectrumAnalysisService
from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.file_processor import FileProcessor
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.utils import Generate, TimeUnit
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import (
    SpectrumRetrievalType,
    WindowFunction,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="CmSpectrumAnalysisService Runner")
    parser.add_argument("--mac", "-m", required=True, help="MAC address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")
    parser.add_argument("--tftp-ipv4", "-t4", required=True, help="IPv4 TFTP server")

    parser.add_argument("--first-segment-center-freq", "-fscf", default="300000000", help="First Segment Center Frequency (Hz)")
    parser.add_argument("--last-segment-center-freq", "-lscf", default="900000000", help="Last Segment Center Frequency (Hz)")
    parser.add_argument("--segment-freq-span", "-sfs", default="1000000", help="Segment Frequency Span (Hz)")
    parser.add_argument("--number-bin-per-segment", "-nbps", default="256", help="Number of bins per segment")
    parser.add_argument("--equivalent-noise-bandwidth", "-enb", default="150", help="Equivalent Noise Bandwidth (kHz)")
    parser.add_argument("--window-function", "-wf", default="1", help="Window Function (HANN=1)")
    parser.add_argument("--number-of-averages", "-noa", default="1", help="Number of averages per segment")
    parser.add_argument("--inactivity-timeout", "-ia", default="300", help="Inactivity timeout (seconds)")
    parser.add_argument("--retrieval-type", "-rt", default="2", help="Spectrum Analyzer Retrieval Type (default: FILE=1) FILE=1 | SNMP=2")

    args = parser.parse_args()

    # Initialize CableModem
    cm = CableModem(
        mac_address=MacAddress(args.mac),
        inet=Inet(args.inet),
        write_community=str(args.community_write)
    )

    # Check modem reachability
    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address()} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    # Build SpectrumAnalyzerParameters from parsed args
    spec_params = SpecAnCapturePara(
        inactivity_timeout=int(args.inactivity_timeout),
        first_segment_center_freq=int(args.first_segment_center_freq),
        last_segment_center_freq=int(args.last_segment_center_freq),
        segment_freq_span=int(args.segment_freq_span),
        num_bins_per_segment=int(args.number_bin_per_segment),
        noise_bw=int(args.equivalent_noise_bandwidth),
        window_function=WindowFunction(int(args.window_function)),
        num_averages=int(args.number_of_averages),
        spectrum_retrieval_type=SpectrumRetrievalType(int(args.retrieval_type)),
    )

    # Create service with the parameter object
    service = CmSpectrumAnalysisService(
        cable_modem=cm,
        capture_parameters=spec_params,)

    msg_rsp: MessageResponse = await service.set_and_go()

    if msg_rsp.status != ServiceStatusCode.SUCCESS:
        logging.error(f"ERROR: {msg_rsp.status.name}, exiting...")
        exit(1)

    cps = CommonProcessService(msg_rsp)
    msg_rsp = cps.process()

    for payload in msg_rsp.payload:  # type: ignore
        timestamp = Generate.time_stamp(TimeUnit.MILLISECONDS)
        file_path = f"../output/spectrum-analyzer-{timestamp}.json"
        FileProcessor(file_path).write_file(payload)
        logging.info(f"Saved result to: {file_path}")


if __name__ == "__main__":
    asyncio.run(main())
