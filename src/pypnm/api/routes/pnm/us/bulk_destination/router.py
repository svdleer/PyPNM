# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for CMTS bulk data destination configuration.

Endpoint:
- POST /pnm/us/bulk-destination  Auto-detects vendor and configures the correct
                                  TFTP destination table(s) for UTSC/RxMER upload.

  Vendor logic:
  - All vendors:  docsPnmBulkDataTransferCfgTable (standard DOCS-PNM-MIB)
  - Casa only:    docsPnmCcapBulkDataControlTable + PnmTestSelector BITS
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pypnm.api.routes.pnm.us.utsc.schemas import CmtsSnmpConfig
from pypnm.api.routes.pnm.us.utsc.service import CmtsUtscService
from pypnm.api.routes.pnm.us.ofdma.rxmer.service import CmtsUsOfdmaRxMerService
from pypnm.api.routes.pnm.us.ofdma.rxmer.schemas import BulkDestinationsResponse, CasaBulkDestination


class BulkDestinationRequest(BaseModel):
    """Request to configure CMTS bulk data destination for PNM file uploads."""
    cmts: CmtsSnmpConfig
    dest_ip: str = Field(..., description="TFTP server IP address")
    dest_path: str = Field(default="./", description="Destination path on TFTP server")
    index: int = Field(default=1, description="Table row index (1-10)")
    pnm_types: List[str] = Field(
        default=["utsc", "rxmer"],
        description=(
            "PNM test types to associate with this destination (Casa only). "
            "Valid values: 'utsc' (bit8 usTriggeredSpectrumCapture), "
            "'rxmer' (bit5 usOfdmaRxMerPerSubcarrier), 'both'."
        )
    )


class BulkDestinationResponse(BaseModel):
    """Response from bulk destination configuration."""
    success: bool
    vendor: Optional[str] = None
    standard_dest_index: Optional[int] = None
    casa_index: Optional[int] = None
    dest_ip: Optional[str] = None
    pnm_test_selector_hex: Optional[str] = None
    error: Optional[str] = None


class BulkDestinationRouter:
    """Router for CMTS bulk data destination configuration."""

    def __init__(self) -> None:
        self.router = APIRouter(
            prefix="/pnm/us/bulk-destination",
            tags=["PNM Operations - CMTS Bulk Data Destination"]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__routes()

    def __routes(self) -> None:

        @self.router.get(
            "",
            summary="List configured CMTS bulk data destinations",
            response_model=BulkDestinationsResponse,
        )
        async def get_bulk_destinations(
            cmts_ip: str,
            community: str = "public",
            write_community: Optional[str] = None
        ) -> BulkDestinationsResponse:
            """
            List all configured rows in docsPnmBulkDataTransferCfgTable.

            Returns destination indexes, IPs, and protocols.
            Use the returned index as destination_index in /utsc/configure or
            /ofdma/rxmer/start.
            """
            self.logger.info(f"Listing bulk destinations on CMTS {cmts_ip}")
            rxmer_svc = CmtsUsOfdmaRxMerService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            utsc_svc = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await rxmer_svc.get_bulk_destinations()
                resp = BulkDestinationsResponse(**result)

                # Casa: also read docsPnmCcapBulkDataControlTable
                vendor = await utsc_svc.detect_vendor()
                if vendor == 'casa':
                    casa_entries = await utsc_svc.get_bulk_data_control()
                    resp.casa_destinations = [CasaBulkDestination(**e) for e in casa_entries]

                return resp
            finally:
                rxmer_svc.close()
                utsc_svc.close()

        @self.router.post(
            "",
            summary="Configure CMTS bulk data destination for UTSC/RxMER upload",
            response_model=BulkDestinationResponse,
        )
        async def configure_bulk_destination(
            request: BulkDestinationRequest
        ) -> BulkDestinationResponse:
            """
            Auto-detects CMTS vendor and configures the correct destination table(s).

            **All vendors** — configures `docsPnmBulkDataTransferCfgTable` (standard):
            - Sets TFTP IP, port, RowStatus=active

            **Casa only** — additionally configures `docsPnmCcapBulkDataControlTable`:
            - Sets DestIpAddr, UploadControl=autoUpload, PnmTestSelector BITS:
              - `'utsc'`  → bit8 `usTriggeredSpectrumCapture`
              - `'rxmer'` → bit5 `usOfdmaRxMerPerSubcarrier`
              - `'both'`  → bit5 + bit8

            Must be called once after CMTS reload before captures upload to TFTP.
            """
            self.logger.info(
                f"Configuring bulk destination index={request.index} "
                f"dest={request.dest_ip} types={request.pnm_types} "
                f"on CMTS {request.cmts.cmts_ip}"
            )

            utsc_svc = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            rxmer_svc = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )

            try:
                # 1. Detect vendor
                vendor = await utsc_svc.detect_vendor()
                self.logger.info(f"Detected vendor: {vendor}")

                response = BulkDestinationResponse(
                    success=True,
                    vendor=vendor,
                    dest_ip=request.dest_ip
                )

                # 2. Standard table — all vendors (Cisco, CommScope, Casa)
                std_result = await rxmer_svc.create_bulk_destination(
                    tftp_ip=request.dest_ip,
                    port=69,
                    local_store=True,
                    dest_index=request.index
                )
                if not std_result.get('success'):
                    self.logger.warning(f"Standard dest table failed: {std_result.get('error')}")
                    response.success = False
                    response.error = std_result.get('error')
                else:
                    response.standard_dest_index = std_result.get('destination_index', request.index)

                # 3. Casa-only: docsPnmCcapBulkDataControlTable + PnmTestSelector
                if vendor == 'casa':
                    casa_result = await utsc_svc.configure_bulk_data_control(
                        dest_ip=request.dest_ip,
                        dest_path=request.dest_path,
                        index=request.index,
                        pnm_types=request.pnm_types
                    )
                    if not casa_result.get('success'):
                        self.logger.warning(f"Casa bulk control failed: {casa_result.get('error')}")
                    else:
                        response.casa_index = casa_result.get('index', request.index)
                        response.pnm_test_selector_hex = casa_result.get('pnm_test_selector_hex')

                return response

            finally:
                utsc_svc.close()
                rxmer_svc.close()


# Required for dynamic auto-registration
router = BulkDestinationRouter().router
