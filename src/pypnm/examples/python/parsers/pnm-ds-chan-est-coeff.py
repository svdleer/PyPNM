#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmChanEstimateCoef import (
    CmDsOfdmChanEstimateCoef,
    CmDsOfdmChanEstimateCoefModel,
)


def main() -> None:
    """
    Parse A Downstream OFDM Channel Estimation Binary File And Print The PNM Model As JSON.

    Usage:

        cd ~/Projects/PyPNM
        python3 src/pypnm/examples/python/parsers/pnm-ds-chan-estimate.py

    The example expects the channel estimation capture at
    ``test/files/channel_estimation.bin`` relative to the project root.
    """
    pfile: Path        = Path("tests/files/channel_estimation.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmDsOfdmChanEstimateCoef(raw_payload)
    parser_model: CmDsOfdmChanEstimateCoefModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
