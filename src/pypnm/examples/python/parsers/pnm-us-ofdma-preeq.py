#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmUsOfdmaPreEq import CmUsOfdmaPreEq, CmUsOfdmaPreEqModel


def main() -> None:
    """
    Parse An Upstream OFDMA Pre-Equalization Binary File And Print The PNM Model As JSON.

    Usage:

        cd ~/Projects/PyPNM
        ./src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq.py

    The example expects the upstream OFDMA pre-equalization capture at
    ``tests/files/us_pre_equalizer_coef.bin`` relative to the project root.
    """
    pfile: Path        = Path("tests/files/us_pre_equalizer_coef.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmUsOfdmaPreEq(raw_payload)
    parser_model: CmUsOfdmaPreEqModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
