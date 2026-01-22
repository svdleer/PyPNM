## Agent Review Bundle Summary
- Goal: Update extended types to use a Python 3.10-compatible string enum.
- Changes: Replaced the Enum with the shared StringEnum shim and added SPDX header.
- Files: src/pypnm/api/routes/common/extended/types.py
- Tests: python3 -m compileall src; ruff check src (fails: pre-existing import/unused issues); ruff format --check . (fails: would reformat many files); pytest -q (510 passed, 3 skipped: PNM_CM_IT gated).
- Notes: None.

# FILE: src/pypnm/api/routes/common/extended/types.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pypnm.lib.types import StringEnum


class CommonMessagingServiceExtension(StringEnum):
    SPECTRUM_ANALYSIS_SNMP_CAPTURE_PARAMETER = "spectrum_analysis_snmp_capture_parameters"
