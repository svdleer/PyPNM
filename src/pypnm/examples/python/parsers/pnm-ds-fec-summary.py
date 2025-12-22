#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmFecSummary import (
    CmDsOfdmFecSummary,
    CmDsOfdmFecSummaryModel,
)


def main() -> None:
    """
    Parse A Downstream OFDM FEC Summary Binary File And Print The PNM Model As JSON.

    Usage:

        cd ~/Projects/PyPNM
        python3 src/pypnm/examples/python/parsers/pnm-ds-fec-summary.py

    The example expects the FEC summary capture at
    ``tests/files/fec_summary.bin`` relative to the project root.
    """
    pfile: Path        = Path("tests/files/fec_summary.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmDsOfdmFecSummary(raw_payload)
    parser_model: CmDsOfdmFecSummaryModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
