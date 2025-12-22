#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia


from __future__ import annotations

from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmRxMer import CmDsOfdmRxMer, CmDsOfdmRxMerModel


def main() -> None:
    """
    Parse A Downstream OFDM RxMER Binary File And Print The PNM Model As JSON.

    This example demonstrates how to:
    1. Load a raw RxMER capture file using ``FileProcessor``.
    2. Decode the payload with ``CmDsOfdmRxMer``.
    3. Convert the parsed result into a typed ``CmDsOfdmRxMerModel``.
    4. Emit the model as pretty-printed JSON on stdout.
    """
    pfile: Path        = Path("tests/files/rxmer.bin")
    raw_payload: bytes = FileProcessor(pfile).read_file()

    parser = CmDsOfdmRxMer(raw_payload)
    parser_model: CmDsOfdmRxMerModel = parser.to_model()

    print(parser_model.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
