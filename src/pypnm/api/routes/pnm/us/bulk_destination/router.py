# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for Casa CCAP docsPnmCcapBulkDataControl configuration.

Endpoint:
- POST /pnm/us/bulk-destination  Configure TFTP destination and PnmTestSelector
                                  for UTSC and/or US OFDMA RxMER file upload.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pypnm.api.routes.pnm.us.utsc.schemas import CmtsSnmpConfig
from pypnm.api.routes.pnm.us.utsc.service import CmtsUtscService


class BulkDestinationRequest(BaseModel):
    """Request to configure docsPnmCcapBulkDataControlTable on a Casa CCAP."""
    cmts: CmtsSnmpConfig
    dest_ip: str = Field(..., description="TFTP server IP address")
    dest_path: str = Field(default="./", description="Destination path on TFTP server")
    index: int = Field(default=1, description="Table row index (1-10)")
    pnm_types: List[str] = Field(
        default=["utsc", "rxmer"],
        description=(
            "PNM test types to associate with this destination. "
            "Valid values: 'utsc' (bit8 usTriggeredSpectrumCapture), "
            "'rxmer' (bit5 usOfdmaRxMerPerSubcarrier), 'both'."
        )
    )


class BulkDestinationResponse(BaseModel):
    """Response from bulk destination configuration."""
    success: bool
    index: int = Field(default=1)
    dest_ip: Optional[str] = None
    pnm_test_selector_hex: Optional[str] = None
    error: Optional[str] = None


class BulkDestinationRouter:
    """Router for Casa CCAP bulk data destination configuration."""

    def __init__(self) -> None:
        self.router = APIRouter(
            prefix="/pnm/us/bulk-destination",
            tags=["PNM Operations - Casa CCAP Bulk Data Destination"]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__routes()

    def __routes(self) -> None:

        @self.router.post(
            "",
            summary="Configure Casa docsPnmCcapBulkDataControl for UTSC/RxMER upload",
            response_model=BulkDestinationResponse,
        )
        async def configure_bulk_destination(
            request: BulkDestinationRequest
        ) -> BulkDestinationResponse:
            """
            Configure docsPnmCcapBulkDataControlTable on a Casa CCAP (E6000).

            Sets the TFTP destination IP, path, upload mode (autoUpload), and
            PnmTestSelector BITS for the specified PNM test types:

            - **'utsc'**  → bit8 `usTriggeredSpectrumCapture`  (UTSC file upload)
            - **'rxmer'** → bit5 `usOfdmaRxMerPerSubcarrier`   (US OFDMA RxMER upload)
            - **'both'**  → bit5 + bit8

            Must be called once after CMTS reload before UTSC or US RxMER captures
            will upload files to the TFTP server.
            """
            self.logger.info(
                f"Configuring bulk destination index={request.index} "
                f"dest={request.dest_ip} types={request.pnm_types} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            try:
                result = await service.configure_bulk_data_control(
                    dest_ip=request.dest_ip,
                    dest_path=request.dest_path,
                    index=request.index,
                    pnm_types=request.pnm_types
                )
                return BulkDestinationResponse(**result)
            finally:
                service.close()


# Required for dynamic auto-registration
router = BulkDestinationRouter().router
