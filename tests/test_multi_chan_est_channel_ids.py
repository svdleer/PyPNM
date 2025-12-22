# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest

from pypnm.api.routes.advance.multi_ds_chan_est import service as chan_est_service
from pypnm.api.routes.advance.multi_ds_chan_est.service import (
    MultiChannelEstimationService,
)
from pypnm.api.routes.common.extended.common_measure_schema import (
    DownstreamOfdmParameters,
)
from pypnm.api.routes.common.extended.common_messaging_service import (
    MessageResponse,
)
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.lib.types import ChannelId


@pytest.mark.asyncio
async def test_multi_chan_est_passes_channel_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[DownstreamOfdmParameters | None] = []

    class _FakeChanEstService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def set_and_go(
            self,
            interface_parameters: DownstreamOfdmParameters | None = None,
        ) -> MessageResponse:
            captured.append(interface_parameters)
            return MessageResponse(ServiceStatusCode.SUCCESS)

    monkeypatch.setattr(chan_est_service, "CmDsOfdmChanEstCoefService", _FakeChanEstService)

    interface_parameters = DownstreamOfdmParameters(channel_id=[ChannelId(193)])
    service = MultiChannelEstimationService(
        cm=object(),
        duration=1,
        interval=1,
        interface_parameters=interface_parameters,
    )

    await service._capture_message_response()

    assert captured == [interface_parameters]
