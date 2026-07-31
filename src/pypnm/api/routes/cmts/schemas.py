# SPDX-License-Identifier: Apache-2.0
# CMTS Modem Discovery Schemas

from __future__ import annotations

import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


def _cm_modem_limit_default() -> int:
    raw = os.environ.get("CM_MODEM_LIMIT", "50000")
    try:
        value = int(raw)
        return max(1, min(value, 50000))
    except (TypeError, ValueError):
        return 50000


class CMTSModemRequest(BaseModel):
    """Request model for CMTS modem discovery."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    community: str = Field(default="public", description="SNMP community for CMTS")
    limit: int = Field(default_factory=_cm_modem_limit_default, description="Maximum number of modems to return")
    enrich: bool = Field(default=False, description="Whether to enrich modems with firmware/model from sysDescr")
    refresh: bool = Field(default=False, description="Bypass cached inventory and perform a live CMTS walk")
    modem_community: str = Field(default="private", description="SNMP community for modem enrichment")
    cmts_hostname: str = Field(default="", description="Optional CMTS hostname stored with inventory")


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
    complete: bool = Field(default=False, description="Whether the inventory walk reached the end of both MAC tables")
    truncated: bool = Field(default=False, description="Whether a MAC table reached the requested walk limit")
    source: Optional[str] = Field(default=None, description="Inventory source")
    requested_limit: Optional[int] = Field(default=None, description="Safety limit used for the inventory walk")
    collected_at: Optional[str] = Field(default=None, description="Inventory collection timestamp")
    critical_oid_errors: Dict[str, str] = Field(default_factory=dict, description="Errors from critical modem MAC tables")
    raw_legacy_mac_count: Optional[int] = Field(default=None, description="Rows returned by the legacy registration MAC table")
    raw_d3_mac_count: Optional[int] = Field(default=None, description="Rows returned by the DOCSIS 3.x registration MAC table")
    enrichment_progress: Optional[Dict[str, int]] = Field(default=None, description="Live enrichment progress: {completed, total}")


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
