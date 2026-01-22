# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import logging

from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.extended.common_process_service import CommonProcessService
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.lib.types import TransactionId, TransactionRecord


def _service_stub(payload: list[dict[str, object]] | None = None) -> CommonProcessService:
    service = CommonProcessService.__new__(CommonProcessService)
    service.logger = logging.getLogger("CommonProcessService")
    service._msg_rsp = MessageResponse(ServiceStatusCode.SUCCESS, payload=payload or [])
    return service


def test_update_pnm_data_from_message_response_extension_merges() -> None:
    service = _service_stub()
    transaction_id = TransactionId("abc123")
    service._msg_rsp.payload = [
        {
            "status": ServiceStatusCode.SUCCESS.name,
            "message_type": "PNM_FILE_TRANSACTION",
            "message": {
                "transaction_id": transaction_id,
                "extension": {"key": "value"},
            },
        },
    ]
    transaction_record: TransactionRecord = {"transaction_id": transaction_id}
    pnm_data = {"existing": "data"}

    updated = service._update_pnm_data_from_message_response_extension(transaction_record, pnm_data)

    assert updated == {"existing": "data", "key": "value"}
    assert transaction_record["transaction_id"] == transaction_id


def test_update_pnm_data_from_message_response_extension_missing_extension() -> None:
    service = _service_stub()
    transaction_id = TransactionId("abc123")
    service._msg_rsp.payload = [
        {
            "status": ServiceStatusCode.SUCCESS.name,
            "message_type": "PNM_FILE_TRANSACTION",
            "message": {
                "transaction_id": transaction_id,
            },
        },
    ]
    transaction_record: TransactionRecord = {"transaction_id": transaction_id}
    pnm_data = {"existing": "data"}

    updated = service._update_pnm_data_from_message_response_extension(transaction_record, pnm_data)

    assert updated == {"existing": "data"}
