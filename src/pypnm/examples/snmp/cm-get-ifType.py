#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import argparse
import asyncio
import json
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.snmp.modules import DocsisIfType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main() -> None:
    parser = argparse.ArgumentParser(description="IfType")
    parser.add_argument("--mac", "-m", required=True, help="MAC address of cable modem")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")

    args = parser.parse_args()

    cm = CableModem(mac_address=MacAddress(args.mac), inet=Inet(args.inet), write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    ofdm_idxs = await cm.getIfTypeIndex(DocsisIfType.docsOfdmDownstream)
    ofdma_idxs = await cm.getIfTypeIndex(DocsisIfType.docsOfdmaUpstream)
    scqam_idxs = await cm.getIfTypeIndex(DocsisIfType.docsCableDownstream)
    atdma_idxs = await cm.getIfTypeIndex(DocsisIfType.docsCableUpstream)

    channel_counts = {
        "SC-QAM": len(scqam_idxs),
        "OFDM": len(ofdm_idxs),
        "ATDMA": len(atdma_idxs),
        "OFDMA": len(ofdma_idxs),
    }

    print(json.dumps(channel_counts, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
