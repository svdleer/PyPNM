#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import argparse
import asyncio
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.cm_snmp_operation import DocsPnmCmCtlStatus, SpectrumRetrievalType
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import (
    DocsIf3CmSpectrumAnalysisCtrlCmd,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="Spectrum Analyzer")
    parser.add_argument("--mac", "-m", required=True, help="Mac address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--tftp-ipv4", "-t4", required=True, help="IPv4 TFTP server")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")

    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    if not await cm.setDocsPnmBulk(tftp_server=args.tftp_ipv4, tftp_path=args.tftp_dest_dir):
        logging.error(f'Unable to set TFTP Server: {args.tftp_ipv4} and/or TFTP Path: {args.tftp_dest_dir}')
        exit(1)

    await cm.setDocsIf3CmSpectrumAnalysisCtrlCmd(DocsIf3CmSpectrumAnalysisCtrlCmd(),
                                                 SpectrumRetrievalType.SNMP )

    while (await cm.getDocsPnmCmCtlStatus() != DocsPnmCmCtlStatus.READY):
        print("Waiting for Spectrum Analyzer to complete")

if __name__ == "__main__":
    asyncio.run(main())
