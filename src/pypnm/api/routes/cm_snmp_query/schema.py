# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── OID definition ───────────────────────────────────────────


class OidEntry(BaseModel):
    """A single OID to query per modem."""
    oid: str = Field(description="OID — numeric (1.3.6.1.2.1.1.3.0) or MIB name (sysUpTime.0)")
    label: str | None = Field(default=None, description="Optional friendly column name for export")


# ── Templates ────────────────────────────────────────────────


class SnmpTemplateCreateRequest(BaseModel):
    name: str = Field(max_length=128)
    description: str | None = Field(default=None, max_length=512)
    oids: list[OidEntry] = Field(min_length=1, max_length=50)


class SnmpTemplate(BaseModel):
    id: int
    name: str
    description: str | None = None
    oids: list[OidEntry] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class SnmpTemplateListResponse(BaseModel):
    status: str = "success"
    templates: list[SnmpTemplate] = Field(default_factory=list)


# ── Job planning ─────────────────────────────────────────────


class SnmpQueryPlanRequest(BaseModel):
    """Create a custom SNMP query job."""
    scope: dict[str, Any] = Field(
        description=(
            '{"type": "cmts", "cmts": ["CMTS-NAME"]} | '
            '{"type": "fiber_node", "cmts": "CMTS-NAME", "fiber_nodes": ["FN01"]} | '
            '{"type": "all_network"}'
        )
    )
    oids: list[OidEntry] = Field(min_length=1, max_length=50)
    max_modems: int | None = Field(default=None, ge=1, le=100000)
    template_id: int | None = Field(default=None, description="Use OIDs from saved template instead of inline list")
    requested_by: str | None = Field(default=None, max_length=64)


class SnmpQueryJobStartRequest(BaseModel):
    max_concurrency: int = Field(default=10, ge=1, le=20)


# ── Job responses ────────────────────────────────────────────


class SnmpQueryJob(BaseModel):
    public_id: str
    status: str
    scope_type: str | None = None
    oids: list[OidEntry] = Field(default_factory=list)
    targets_total: int = 0
    targets_succeeded: int = 0
    targets_failed: int = 0
    targets_pending: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    requested_by: str | None = None
    error_text: str | None = None


class SnmpQueryPlanResponse(BaseModel):
    status: str = "success"
    job: SnmpQueryJob


class SnmpQueryJobListResponse(BaseModel):
    status: str = "success"
    jobs: list[SnmpQueryJob] = Field(default_factory=list)


class SnmpQueryJobDetailResponse(BaseModel):
    status: str = "success"
    job: SnmpQueryJob


class SnmpQueryJobActionResponse(BaseModel):
    status: str = "success"
    job: SnmpQueryJob | None = None
    message: str | None = None


class SnmpQueryTarget(BaseModel):
    id: int
    mac: str
    modem_ip: str | None = None
    cmts: str | None = None
    fiber_node: str | None = None
    state: str = "planned"
    results: dict[str, Any] | None = None
    error_text: str | None = None


class SnmpQueryTargetListResponse(BaseModel):
    status: str = "success"
    targets: list[SnmpQueryTarget] = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False


class SnmpQueryCapabilitiesResponse(BaseModel):
    status: str = "success"
    scope_types: list[str] = Field(
        default_factory=lambda: ["all_network", "cmts", "fiber_node"]
    )
    max_oids: int = 50
    max_concurrency: int = 20
    default_concurrency: int = 10
    max_modems: int = 100000
