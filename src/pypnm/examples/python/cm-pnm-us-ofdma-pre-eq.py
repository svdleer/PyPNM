#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import argparse
import asyncio
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.cm_snmp_operation import DocsPnmCmCtlStatus
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.utils import Generate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="OFDMA Upstream Pre-Equlazation")
    parser.add_argument("--mac", "-m", required=True, help="Mac address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--tftp-ipv4", "-t4", required=True, help="IPv4 TFTP server")
    parser.add_argument("--tftp-ipv6", "-t6", help="IPv6 TFTP server")
    parser.add_argument("--tftp-dest-dir", "-td", default="", help="TFTP server destination directory")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")
    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    if not await cm.setDocsPnmBulk(tftp_server=args.tftp_ipv4, tftp_path=args.tftp_dest_dir):
        logging.error(f'Unable to set TFTP Server: {args.tftp_ipv4} and/or TFTP Path: {args.tftp_dest_dir}')
        exit(1)

    ofdma_idx_list = await cm.getDocsIf31CmUsOfdmaChanChannelIdIndex()

    for idx in ofdma_idx_list:

        filename = f"us-ofdma-pre-eq_{idx}_{Generate.time_stamp()}.bin"
        filename_last = f"us-ofdma-pre-eq-last_{idx}_{Generate.time_stamp()}.bin"
        print(f"Setting Pre-Equalization OFDMA index {idx} with filename {filename}")
        dsce = await cm.setDocsPnmCmUsPreEq(ofdma_idx=idx,
                                            filename=filename,
                                            last_pre_eq_filename=filename_last)

        print(f'Waiting for Pre-Equalization OFDMA to complete,setDocsPnmCmUsPreEq returned: {dsce}')

        while (await cm.getDocsPnmCmCtlStatus() != DocsPnmCmCtlStatus.READY):
            print("Waiting for Pre-Equalization OFDMA to complete")

        print("Done")

if __name__ == "__main__":
    asyncio.run(main())
