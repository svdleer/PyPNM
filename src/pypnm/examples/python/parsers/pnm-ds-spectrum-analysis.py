#!/usr/bin/env python3

from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmSpectrumAnalysis import CmSpectrumAnalysis, CmSpectrumAnalyzerModel


def main() -> None:
    """
    Parse A Downstream Spectrum Analysis Binary File And Print The PNM Model As JSON.

    Usage:

        cd ~/Projects/PyPNM
        ./src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis.py

    The example expects the spectrum analysis capture at
    ``tests/files/spectrum_analyzer.bin`` relative to the project root.
    """
    pfile: Path        = Path("tests/files/spectrum_analyzer.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmSpectrumAnalysis(raw_payload)
    parser_model: CmSpectrumAnalyzerModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
