#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmSpectrumAnalysisSnmp import (
    CmSpectrumAnalysisSnmp,
    CmSpectrumAnalysisSnmpModel,
)


def main() -> None:
    """
    Parse A Downstream Spectrum Analysis SNMP Payload And Print The PNM Model As JSON.

    Usage:

        cd ~/Projects/PyPNM
        ./src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis-snmp.py

    The example expects the spectrum analysis SNMP capture at
    ``tests/files/spectrum_analyzer_snmp.bin`` relative to the project root.
    """
    pfile: Path        = Path("tests/files/spectrum_analyzer_snmp.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmSpectrumAnalysisSnmp(raw_payload)
    parser_model: CmSpectrumAnalysisSnmpModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
