#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import argparse
import asyncio
import json
import logging

from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.data_type.DocsIfUpstreamChannelEntry import DocsIfUpstreamChannelEntry
from pypnm.lib.file_processor import FileProcessor
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.utils import Generate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s")

async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch DOCSIS Upstream Channel Entries via SNMP")
    parser.add_argument("--mac", "-m", required=True, help="MAC address of cable modem (e.g., aa:bb:cc:dd:ee:ff)")
    parser.add_argument("--inet", "-i", required=True, help="IP address of cable modem (e.g., 192.168.0.100)")
    parser.add_argument("--community-write", "-cw", default="private", help="SNMP write community string (default: private)")

    args = parser.parse_args()

    cm = CableModem(
        mac_address=MacAddress(args.mac),
        inet=Inet(args.inet),
        write_community=str(args.community_write))

    if not cm.is_ping_reachable():
        logging.error(f"{cm.get_inet_address()} not reachable, exiting...")
        exit(1)

    logging.info(f"Connected to: {await cm.getSysDescr()}")

    try:
        entries: list[DocsIfUpstreamChannelEntry] = await cm.getDocsIfUpstreamChannelEntry()

        if not entries:
            logging.warning("No upstream channel entries found.")
        else:
            # Convert list of entries to list of dictionaries
            entry_dicts = [entry.model_dump() for entry in entries]
            json_out = json.dumps(entry_dicts, indent=2)

            # Write to file
            filename = f".data/pnm/DocsIfUpstreamChannelEntry-{Generate.time_stamp()}.json"
            FileProcessor(filename).write_file(json_out)
            logging.info(f"✅ Output written to: {filename}")

    except Exception as e:
        logging.exception(f"An error occurred while fetching upstream channel entries., reason: {e}")

if __name__ == "__main__":
    asyncio.run(main())
