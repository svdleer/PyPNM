# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel

from pypnm.api.routes.docs.pnm.spectrumAnalyzer.schemas import SpecAnCapturePara
from pypnm.lib.types import StringEnum


class CommonMessagingServiceExtension(StringEnum):
    SPECTRUM_ANALYSIS_SNMP_CAPTURE_PARAMETER = "spectrum_analysis_snmp_capture_parameters"

class CommonMsgServiceExtParams(BaseModel):
    spectrum_analysis_snmp_capture_parameters: SpecAnCapturePara

class CommonMessagingServiceExtensionModel(BaseModel):
    extension: CommonMsgServiceExtParams
