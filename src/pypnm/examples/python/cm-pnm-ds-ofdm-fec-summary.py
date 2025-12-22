#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import argparse
import asyncio
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.cm_snmp_operation import DocsPnmCmCtlStatus, FecSummaryType
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.utils import Generate

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="Downstream FEC Summary")
    parser.add_argument("--mac", "-m", required=True, help="MAC address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--tftp-ipv4", "-t4", required=True, help="IPv4 TFTP server")
    parser.add_argument("--tftp-ipv6", "-t6", help="IPv6 TFTP server (optional)")
    parser.add_argument("--tftp-dest-dir", "-td", default="", help="TFTP server destination directory")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")
    parser.add_argument("--summary-type", "-st", default="10min", choices=["10min", "24hr"], help="FEC Summary Report [10min] | 24hr (default: 10min)")

    args = parser.parse_args()

    # Initialize CableModem object
    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    # Check if the cable modem is reachable
    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    # Get OFDM channel entries
    oce_list = await cm.getDocsIf31CmDsOfdmChanEntry()

    if not oce_list:
        logging.error('Unable to get DocsIf31CmDsOfdmChanEntry')
        exit(1)

    # Set TFTP server and path
    if not await cm.setDocsPnmBulk(tftp_server=args.tftp_ipv4, tftp_path=args.tftp_dest_dir):
        logging.error(f'Unable to set TFTP Server: {args.tftp_ipv4} and/or TFTP Path: {args.tftp_dest_dir}')
        exit(1)

    # Loop over OFDM channels and set FEC summary
    for oce in oce_list:
        idx = oce.index
        filename = f"fec_summary_{idx}_{Generate.time_stamp()}.bin"
        logging.info(f"Setting FEC Summary for OFDM index {idx} with filename {filename}")

        # Determine FEC summary type based on user input
        if args.summary_type == "10min":
            sum_type = FecSummaryType.TEN_MIN
        else:
            sum_type = FecSummaryType.TWENTY_FOUR_HOUR

        # Set FEC summary
        if not await cm.setDocsPnmCmDsOfdmFecSum(ofdm_idx=idx, fec_sum_file_name=filename, fec_sum_type=sum_type):
            logging.error(f'Unable to start FEC Summary for OFDM index {idx}')
            exit(1)

        # Wait for testing to finish
        while True:
            if await cm.getDocsPnmCmCtlStatus() == DocsPnmCmCtlStatus.TEST_IN_PROGRESS:
                logging.info(f'Test in progress for OFDM index {idx}...')
                continue
            break

    logging.info("FEC Summary setup completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())
