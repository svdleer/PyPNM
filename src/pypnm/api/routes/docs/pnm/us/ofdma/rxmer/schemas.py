# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Schemas for CMTS Upstream OFDMA RxMER operations.

This module provides Pydantic models for CMTS-side US OFDMA RxMER
measurements as defined in DOCS-PNM-MIB (docsPnmCmtsUsOfdmaRxMerTable).
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class CmtsSnmpConfig(BaseModel):
    """CMTS SNMP configuration."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    community: str = Field(default="private", description="SNMP community string")
    write_community: Optional[str] = Field(default=None, description="SNMP write community (defaults to community)")


class UsOfdmaRxMerDiscoverRequest(BaseModel):
    """Request to discover modem's OFDMA channel on CMTS."""
    cmts: CmtsSnmpConfig
    cm_mac_address: str = Field(..., description="Cable modem MAC address")


class UsOfdmaRxMerDiscoverResponse(BaseModel):
    """Response from OFDMA channel discovery."""
    success: bool
    cm_mac_address: str
    cm_index: Optional[int] = None
    ofdma_ifindex: Optional[int] = None
    ofdma_description: Optional[str] = None
    error: Optional[str] = None


class UsOfdmaRxMerStartRequest(BaseModel):
    """Request to start US OFDMA RxMER measurement."""
    cmts: CmtsSnmpConfig
    ofdma_ifindex: int = Field(..., description="OFDMA channel ifIndex on CMTS")
    cm_mac_address: str = Field(..., description="Cable modem MAC address")
    filename: str = Field(default="us_rxmer", description="Output filename")
    pre_eq: bool = Field(default=True, description="Enable pre-equalization")
    num_averages: int = Field(default=1, ge=1, le=255, description="Number of averages")
    destination_index: int = Field(
        default=0,
        ge=0,
        description="Bulk transfer destination index. 0=local storage only, "
                    ">0=use docsPnmBulkDataTransferCfgTable row for TFTP upload"
    )


class UsOfdmaRxMerStartResponse(BaseModel):
    """Response from starting US OFDMA RxMER measurement."""
    success: bool
    ofdma_ifindex: Optional[int] = None
    cm_mac_address: Optional[str] = None
    filename: Optional[str] = None
    destination_index: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class UsOfdmaRxMerStatusRequest(BaseModel):
    """Request to get US OFDMA RxMER measurement status."""
    cmts: CmtsSnmpConfig
    ofdma_ifindex: int = Field(..., description="OFDMA channel ifIndex on CMTS")


class UsOfdmaRxMerStatusResponse(BaseModel):
    """Response with US OFDMA RxMER measurement status."""
    success: bool
    ofdma_ifindex: Optional[int] = None
    meas_status: Optional[int] = None
    meas_status_name: Optional[str] = None
    is_ready: bool = False
    is_busy: bool = False
    is_error: bool = False
    error: Optional[str] = None


class BulkDestination(BaseModel):
    """Bulk data transfer destination configuration."""
    index: int = Field(..., description="Destination index for use in destination_index parameter")
    ip_address: Optional[str] = Field(None, description="Destination IP address")
    port: int = Field(default=69, description="Destination port (default 69 for TFTP)")
    protocol: str = Field(default="tftp", description="Transfer protocol")
    local_store: bool = Field(default=True, description="Whether to also store locally")


class BulkDestinationsRequest(BaseModel):
    """Request to get bulk transfer destinations."""
    cmts: CmtsSnmpConfig


class BulkDestinationsResponse(BaseModel):
    """Response with list of bulk transfer destinations."""
    success: bool
    destinations: list[BulkDestination] = Field(default_factory=list)
    error: Optional[str] = None
