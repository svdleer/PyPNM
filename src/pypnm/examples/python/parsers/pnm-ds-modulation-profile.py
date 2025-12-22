#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmModulationProfile import CmDsOfdmModulationProfile
from pypnm.pnm.parser.model.parser_rtn_models import CmDsOfdmModulationProfileModel


def main() -> None:
    """
    Parse A Downstream OFDM Modulation Profile Binary File And Print The PNM Model As JSON.

    Usage:

        cd ~/Projects/PyPNM
        ./src/pypnm/examples/python/parsers/pnm-ds-modulation-profile.py

    The example expects the modulation profile capture at
    ``tests/files/modulation_profile.bin`` relative to the project root.
    """
    pfile: Path        = Path("tests/files/modulation_profile.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmDsOfdmModulationProfile(raw_payload)
    parser_model: CmDsOfdmModulationProfileModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
