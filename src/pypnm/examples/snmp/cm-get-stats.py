#!/usr/bin/env python3

from __future__ import annotations

import argparse

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import asyncio
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch DocsPnmBulkDataGroup via SNMP")
    parser.add_argument("--mac", "-m", required=True, help="Mac address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")
    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    '''
    rtn = await cm.getIfTypeIndex(DocsisIfType.docsCableMaclayer)
    logging.info(f"IfTypeIndex: {rtn}")

    rtn = await cm.getSysDescr()
    logging.info(f"SysDescr: {rtn}")

    rtn = await cm.getDocsPnmCmCtlStatus()
    logging.info(f"DocsPnmCmCtlStatus: {rtn}")

    rtn = await cm.getIfPhysAddress()
    logging.info(f"DocsPnmCmCtlStatus: {rtn}")

    rtn = await cm.getDocsIf31CmDsOfdmChanChannelIdIndex()
    logging.info(f"getDocsIf31CmDsOfdmChanChannelIdIndex: {rtn}")

    rtn = await cm.getDocsIf31CmUsOfdmaChanChannelIdIndex()
    logging.info(f"getDocsIf31CmUsOfdmaChanChannelIdIndex: {rtn}")

    rtn = await cm.getDocsIf31CmDsOfdmChanPlcFreq()
    logging.info(f"getDocsIf31CmDsOfdmChanPlcFreq: {rtn}")

    for idx in await cm.getDocsIf31CmDsOfdmChanChannelIdIndex():
        rtn = await cm.getDocsPnmCmOfdmChEstCoefMeasStatus(idx)
        logging.info(f"getDocsPnmCmOfdmChEstCoefMeasStatus: {rtn}")

    for idx in await cm.getDocsIf31CmDsOfdmChanChannelIdIndex():
        rtn = await cm.getCmDsOfdmProfileStatsConfigChangeCt(idx)
        logging.info(f"getCmDsOfdmProfileStatsConfigChangeCt: {rtn}")

    rtn = await cm.getDocsIf31CmDsOfdmChanEntry()
    logging.info(f'getDocsIf31CmDsOfdmChanEntry -> {rtn}')
    '''

    rtn = await cm.getDocsPnmBulkDataGroup()
    logging.info(f'getDocsPnmBulkDataGroup -> {rtn}')

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
