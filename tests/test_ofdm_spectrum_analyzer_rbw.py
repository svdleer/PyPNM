# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest

from pypnm.api.routes.common.extended.common_messaging_service import (
    MessageResponse,
)
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.spectrumAnalyzer import service as spectrum_service
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.abstract.com_spec_chan_ana import (
    CommonChannelSpectumBwLut,
)
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.schemas import SpecAnCapturePara
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.service import (
    DsOfdmChannelSpectrumAnalyzer,
)
from pypnm.lib.conversions.rbw import RBWConversion
from pypnm.lib.types import ChannelId, FrequencyHz, ResolutionBw


class _FakeCableModem:
    def __init__(self) -> None:
        self._mac = "aa:bb:cc:dd:ee:ff"

    @property
    def get_mac_address(self) -> str:
        return self._mac


class _TestOfdmAnalyzer(DsOfdmChannelSpectrumAnalyzer):
    async def calculate_channel_spectrum_bandwidth(self) -> CommonChannelSpectumBwLut:
        return {
            ChannelId(1): (
                FrequencyHz(100_000_000),
                FrequencyHz(110_000_000),
                FrequencyHz(120_000_000),
            )
        }

    async def updatePnmMeasurementStatistics(self, channel_id: ChannelId) -> bool:
        return True


@pytest.mark.asyncio
async def test_ofdm_analyzer_uses_resolution_bandwidth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[SpecAnCapturePara] = []

    class _FakeOfdmChanSpecAnalyzerService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self._params: SpecAnCapturePara | None = None

        def setSpectrumCaptureParameters(self, capture_parameters: SpecAnCapturePara) -> None:
            self._params = capture_parameters
            captured.append(capture_parameters)

        async def set_and_go(self) -> MessageResponse:
            return MessageResponse(ServiceStatusCode.SUCCESS)

    monkeypatch.setattr(
        spectrum_service,
        "OfdmChanSpecAnalyzerService",
        _FakeOfdmChanSpecAnalyzerService,
    )

    analyzer = _TestOfdmAnalyzer(
        cable_modem=_FakeCableModem(),
        number_of_averages=1,
        resolution_bandwidth_hz=ResolutionBw(250_000),
    )

    await analyzer.start()

    assert len(captured) == 1

    rbw_settings = RBWConversion.getSpectrumRbwSetttings(ResolutionBw(250_000))
    assert captured[0].num_bins_per_segment == rbw_settings[1]
    assert captured[0].segment_freq_span == FrequencyHz(rbw_settings[2])
