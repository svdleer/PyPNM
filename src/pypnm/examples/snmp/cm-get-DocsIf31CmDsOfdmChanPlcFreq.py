#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import argparse
import asyncio
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="getDocsIf31CmDsOfdmChanPlcFreq")
    parser.add_argument("--mac", "-m", required=True, help="MAC address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")

    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    logging.info(f'Mac: {cm.get_mac_address} - Inet: {cm.get_inet_address} - Fetching all OFDM(s)')

    idx_plc_l = await cm.getDocsIf31CmDsOfdmChanPlcFreq()

    for idx_plc in idx_plc_l:
        logging.info(f'Mac: {cm.get_mac_address} - Inet: {cm.get_inet_address} - OFDM-IDX: {idx_plc[0]} - PLC: {idx_plc[1]}')

if __name__ == "__main__":
    asyncio.run(main())
