# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pypnm.api.routes.common.classes.analysis.analysis import Analysis, AnalysisType
from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode


def test_analysis_extracts_snmp_capture_parameters() -> None:
    capture_parameters = {
        "inactivity_timeout": 120,
        "first_segment_center_freq": 262000000,
        "last_segment_center_freq": 1030000000,
        "segment_freq_span": 30000000,
        "num_bins_per_segment": 100,
        "noise_bw": 150,
        "window_function": 1,
        "num_averages": 1,
        "spectrum_retrieval_type": 2,
    }
    payload = [
        {
            "status": "SUCCESS",
            "spectrum_analysis_snmp_capture_parameters": capture_parameters,
            "mac_address": "aa:bb:cc:dd:ee:ff",
        }
    ]
    msg_response = MessageResponse(ServiceStatusCode.SUCCESS, payload=payload)

    analysis = Analysis(
        analysis_type=AnalysisType.BASIC,
        msg_response=msg_response,
        skip_automatic_process=True,
    )

    assert analysis._msg_rsp_extension == capture_parameters
