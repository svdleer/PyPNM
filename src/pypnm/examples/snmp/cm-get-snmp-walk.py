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
from pypnm.snmp.compiled_oids import COMPILED_OIDS
from pypnm.snmp.snmp_v2c import Snmp_v2c


async def main() -> None:
    parser = argparse.ArgumentParser(description="SNMP Get Next")
    parser.add_argument("--mac", "-m", required=True, help="Mac address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")
    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    _pysnmp = Snmp_v2c(Inet(cm.get_inet_address))

    result = await _pysnmp.walk(COMPILED_OIDS['docsIf31CmDsOfdmChanChannelId'])

    if result is None:
        logging.error("Not able to get OFDM Indexes...")
        exit(1)

    print(_pysnmp.snmp_get_result_value(result))

if __name__ == "__main__":
    asyncio.run(main())
