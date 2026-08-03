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
    collect_cpe: bool = Field(default=False, description="Collect DOCS-SUBMGT3 CPE addresses for scheduled inventory")
    modem_community: str = Field(default="private", description="SNMP community for modem enrichment")
    cmts_hostname: str = Field(default="", description="Optional CMTS hostname stored with inventory")


class CPECollectionRequest(BaseModel):
    """Request model for the dedicated scheduled CPE collection."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    community: str = Field(default="public", description="SNMP community for CMTS")
    limit: Optional[int] = Field(default=None, ge=1, le=500000)


class CPECollectionResponse(BaseModel):
    """One validated CPE-address generation from a CMTS."""
    success: bool
    cpe_addresses: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    complete: bool = False
    truncated: bool = False
    requested_limit: Optional[int] = None
    collected_at: Optional[str] = None
    oid_errors: Dict[str, str] = Field(default_factory=dict)
    validation_error: Optional[str] = None
    raw_d3_mac_count: Optional[int] = None
    raw_cpe_type_count: Optional[int] = None
    raw_cpe_address_count: Optional[int] = None
    raw_cpe_prefix_count: Optional[int] = None
    error: Optional[str] = None


class ModemInfo(BaseModel):
    """Modem information from CMTS discovery."""
    mac_address: str = Field(..., description="Modem MAC address")
    cmts_index: Optional[str] = Field(default=None, description="Legacy/display CMTS registration index")
    docsif3_index: Optional[str] = Field(default=None, description="DOCS-IF3 registration index used by DOCSIS 3.1 augmentation tables")
    ip_address: Optional[str] = Field(default=None, description="Modem IP address")
    status: Optional[str] = Field(default=None, description="Registration status (operational, ranging, etc)")
    status_code: Optional[int] = Field(default=None, description="Raw status code from CMTS")
    docsis_version: Optional[str] = Field(default=None, description="DOCSIS version (1.0, 1.1, 2.0, 3.0, 3.1)")
    partial_service: Optional[bool] = Field(default=None, description="Whether modem is in partial service in either direction")
    partial_service_downstream: Optional[bool] = Field(default=None, description="Whether downstream is in partial service")
    partial_service_upstream: Optional[bool] = Field(default=None, description="Whether upstream is in partial service")
    partial_service_state: Optional[str] = Field(default=None, description="Partial service state: other, none, downstream, upstream, both, or unknown")
    vendor: Optional[str] = Field(default=None, description="Vendor from MAC OUI or sysDescr")
    model: Optional[str] = Field(default=None, description="Model from sysDescr")
    software_version: Optional[str] = Field(default=None, description="Software/firmware version from sysDescr")
    firmware: Optional[str] = Field(default=None, description="Firmware from CMTS (if available)")
    upstream_interface: Optional[str] = Field(default=None, description="Upstream interface name")
    upstream_ifindex: Optional[int] = Field(default=None, description="Upstream interface ifIndex")
    upstream_channel_id: Optional[int] = Field(default=None, description="Upstream channel ID")
    cable_mac: Optional[str] = Field(default=None, description="Cable MAC interface name")
    ofdm_ifindex: Optional[int] = Field(default=None, description="OFDM downstream ifIndex (D3.1)")
    ofdma_ifindex: Optional[int] = Field(default=None, description="OFDMA upstream ifIndex (D3.1)")
    ofdm_channel_count: Optional[int] = Field(default=None, description="Number of assigned OFDM channels")
    ofdma_channel_count: Optional[int] = Field(default=None, description="Number of assigned OFDMA channels")


class CMTSModemResponse(BaseModel):
    """Response model for CMTS modem discovery."""
    success: bool = Field(..., description="Whether the request was successful")
    modems: List[Dict[str, Any]] = Field(default_factory=list, description="List of discovered modems")
    count: int = Field(default=0, description="Number of modems returned")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of the response")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    enriched: bool = Field(default=False, description="Whether direct per-modem metadata enrichment has completed")
    capability_enriched: bool = Field(default=False, description="Whether authoritative CMTS capability tables were successfully collected for this generation")
    cached: bool = Field(default=False, description="Whether result came from cache")
    enriching: bool = Field(default=False, description="Whether enrichment is in progress")
    complete: bool = Field(default=False, description="Whether the inventory walk reached the end of both MAC tables")
    truncated: bool = Field(default=False, description="Whether a MAC table reached the requested walk limit")
    source: Optional[str] = Field(default=None, description="Inventory source")
    requested_limit: Optional[int] = Field(default=None, description="Safety limit used for the inventory walk")
    collected_at: Optional[str] = Field(default=None, description="Inventory collection timestamp")
    revision_at: Optional[str] = Field(default=None, description="Latest full or targeted inventory revision timestamp")
    critical_oid_errors: Dict[str, str] = Field(default_factory=dict, description="Errors from critical modem MAC tables")
    raw_legacy_mac_count: Optional[int] = Field(default=None, description="Rows returned by the legacy registration MAC table")
    raw_d3_mac_count: Optional[int] = Field(default=None, description="Rows returned by the DOCSIS 3.x registration MAC table")
    cpe_addresses: List[Dict[str, Any]] = Field(default_factory=list, description="CPE addresses collected for scheduled persistence")
    cpe_complete: bool = Field(default=False, description="Whether all requested CPE address columns completed")
    cpe_truncated: bool = Field(default=False, description="Whether a CPE address column reached the walk limit")
    cpe_oid_errors: Dict[str, str] = Field(default_factory=dict, description="Errors from CPE address columns")
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
