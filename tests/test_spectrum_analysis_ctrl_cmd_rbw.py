# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026

from __future__ import annotations

from pypnm.lib.types import ResolutionBw
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import (
    DocsIf3CmSpectrumAnalysisCtrlCmd,
)


def test_auto_scale_rbw_adjusts_frequency_span() -> None:
    cmd = DocsIf3CmSpectrumAnalysisCtrlCmd(
        docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency=100_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency=105_050_000,
        docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan=1_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment=10,
    )

    status, changed = cmd.autoScaleSpectrumAnalyzerRbw(ResolutionBw(100_000), True)

    assert status is True
    assert changed is True
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan == 1_000_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency == 100_025_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency == 105_025_000


def test_auto_scale_rbw_selects_segment_span_without_frequency_shift() -> None:
    cmd = DocsIf3CmSpectrumAnalysisCtrlCmd(
        docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency=100_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency=105_200_000,
        docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan=1_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment=10,
    )

    status, changed = cmd.autoScaleSpectrumAnalyzerRbw(ResolutionBw(100_000), False)

    assert status is True
    assert changed is True
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan == 1_040_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency == 100_000_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency == 105_200_000
