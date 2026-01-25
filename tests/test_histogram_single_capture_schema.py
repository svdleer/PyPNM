# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pypnm.api.routes.docs.pnm.ds.histogram.schemas import (
    PnmHistogramSingleCaptureRequest,
)


def test_histogram_schema_rejects_capture_channel_ids() -> None:
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
        },
        "capture_settings": {
            "sample_duration": 10,
        },
    }

    with pytest.raises(ValidationError):
        PnmHistogramSingleCaptureRequest.model_validate(payload)
