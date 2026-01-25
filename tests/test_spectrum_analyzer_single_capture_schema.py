# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pypnm.api.routes.docs.pnm.spectrumAnalyzer.schemas import (
    SingleCaptureSpectrumAnalyzerRequest,
)


def test_single_capture_schema_rejects_capture_channel_ids() -> None:
    payload = {
        "cable_modem": {
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "ip_address": "192.168.0.100",
            "pnm_parameters": {
                "tftp": {
                    "ipv4": "192.168.0.10",
                    "ipv6": "2001:db8::10",
                },
                "capture": {
                    "channel_ids": [1, 2],
                },
            },
            "snmp": {
                "snmpV2C": {
                    "community": "private",
                },
            },
        },
        "analysis": {
            "type": "basic",
            "output": {"type": "json"},
            "plot": {"ui": {"theme": "dark"}},
            "spectrum_analysis": {"moving_average": {"points": 10}},
        },
        "capture_parameters": {
            "inactivity_timeout": 60,
            "first_segment_center_freq": 300000000,
            "last_segment_center_freq": 900000000,
            "segment_freq_span": 1000000,
            "num_bins_per_segment": 256,
            "noise_bw": 150,
            "window_function": 1,
            "num_averages": 1,
            "spectrum_retrieval_type": 1,
        },
    }

    with pytest.raises(ValidationError):
        SingleCaptureSpectrumAnalyzerRequest.model_validate(payload)
