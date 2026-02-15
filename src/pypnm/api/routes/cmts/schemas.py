# SPDX-License-Identifier: Apache-2.0
# CMTS Modem Discovery Schemas

from __future__ import annotations

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class CMTSModemRequest(BaseModel):
    """Request model for CMTS modem discovery."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    community: str = Field(default="public", description="SNMP community for CMTS")
    limit: int = Field(default=10000, description="Maximum number of modems to return")
    enrich: bool = Field(default=False, description="Whether to enrich modems with firmware/model from sysDescr")
    modem_community: str = Field(default="private", description="SNMP community for modem enrichment")


class ModemInfo(BaseModel):
    """Modem information from CMTS discovery."""
    mac_address: str = Field(..., description="Modem MAC address")
    cmts_index: Optional[str] = Field(default=None, description="CMTS registration index")
    ip_address: Optional[str] = Field(default=None, description="Modem IP address")
    status: Optional[str] = Field(default=None, description="Registration status (operational, ranging, etc)")
    status_code: Optional[int] = Field(default=None, description="Raw status code from CMTS")
    docsis_version: Optional[str] = Field(default=None, description="DOCSIS version (1.0, 1.1, 2.0, 3.0, 3.1)")
    partial_service: Optional[bool] = Field(default=None, description="Whether modem is in partial service")
    vendor: Optional[str] = Field(default=None, description="Vendor from MAC OUI or sysDescr")
    model: Optional[str] = Field(default=None, description="Model from sysDescr")
    software_version: Optional[str] = Field(default=None, description="Software/firmware version from sysDescr")
    firmware: Optional[str] = Field(default=None, description="Firmware from CMTS (if available)")
    upstream_interface: Optional[str] = Field(default=None, description="Upstream interface name")
    upstream_ifindex: Optional[int] = Field(default=None, description="Upstream interface ifIndex")
    upstream_channel_id: Optional[int] = Field(default=None, description="Upstream channel ID")
    cable_mac: Optional[str] = Field(default=None, description="Cable MAC interface name")
    ofdma_ifindex: Optional[int] = Field(default=None, description="OFDMA upstream ifIndex (D3.1)")


class CMTSModemResponse(BaseModel):
    """Response model for CMTS modem discovery."""
    success: bool = Field(..., description="Whether the request was successful")
    modems: List[Dict[str, Any]] = Field(default_factory=list, description="List of discovered modems")
    count: int = Field(default=0, description="Number of modems returned")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of the response")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    enriched: bool = Field(default=False, description="Whether modems have been enriched")
    cached: bool = Field(default=False, description="Whether result came from cache")
    enriching: bool = Field(default=False, description="Whether enrichment is in progress")


class EnrichModemRequest(BaseModel):
    """Request model for modem enrichment."""
    modems: List[Dict[str, Any]] = Field(..., description="List of modems to enrich")
    modem_community: str = Field(default="private", description="SNMP community for modem queries")


class EnrichModemResponse(BaseModel):
    """Response model for modem enrichment."""
    success: bool = Field(..., description="Whether enrichment was successful")
    modems: List[Dict[str, Any]] = Field(default_factory=list, description="Enriched modems")
    enriched_count: int = Field(default=0, description="Number of modems successfully enriched")
    total_count: int = Field(default=0, description="Total number of modems")
    error: Optional[str] = Field(default=None, description="Error message if failed")
