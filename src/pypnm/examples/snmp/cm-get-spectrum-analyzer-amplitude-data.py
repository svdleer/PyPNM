#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import argparse
import asyncio
import json
import logging
from time import sleep

from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.file_processor import FileProcessor
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.utils import Generate, TimeUnit
from pypnm.pnm.parser.CmSpectrumAnalysisSnmp import CmSpectrumAnalysisSnmp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="Get Spectrum Analyzer AmplitudeData")
    parser.add_argument("--mac", "-m", required=True, help="MAC address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")
    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac),
                    inet=Inet(args.inet),
                    write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    print(f"Connected to: {await cm.getSysDescr()}")

    while not await cm.isAmplitudeDataPresent():
        sleep(1)
        logging.info('Waiting for AmplitudeData is Present')

    logging.info('AmplitudeData is Present....Processing')

    amplitude_byte_stream = await cm.getSpectrumAmplitudeData()
    amplitude_data = CmSpectrumAnalysisSnmp(amplitude_byte_stream)

    filename = f'spec_amplitude_data_{Generate.time_stamp(TimeUnit.MILLISECONDS)}.json'
    FileProcessor(f'../output/{filename}').write_file(json.dumps(amplitude_data.to_dict()))

if __name__ == "__main__":
    asyncio.run(main())
