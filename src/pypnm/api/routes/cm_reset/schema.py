# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Request schemas ──────────────────────────────────────────


class CmResetPlanRequest(BaseModel):
    """Create a reset plan (targets are resolved from scope)."""

    scope: dict[str, Any] = Field(
        description=(
            "Scope definition. "
            '{"type": "single", "mac": "aa:bb:cc:dd:ee:ff"} | '
            '{"type": "cmts", "cmts": ["CMTS-NAME"]} | '
            '{"type": "fiber_node", "cmts": "CMTS-NAME", "fiber_nodes": ["FN01"]} | '
            '{"type": "file", "mac_list": ["aa:bb:...", ...]}'
        )
    )
    scheduled_start: str | None = Field(
        default=None,
        description="ISO-8601 datetime for scheduled execution (must be within 01:00-06:00 window). "
        "Omit for immediate queuing (still respects execution window).",
    )
    requested_by: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)


class CmResetJobStartRequest(BaseModel):
    """Start an already-planned reset job."""

    max_concurrency: int = Field(default=5, ge=1, le=10)
    confirmation_passphrase: str = Field(
        description="Must be exactly: have you tried turning it on and off again?"
    )


class CmResetJobCancelRequest(BaseModel):
    pass


# ── Response schemas ─────────────────────────────────────────


class CmResetJob(BaseModel):
    public_id: str
    status: str
    scope_type: str | None = None
    targets_total: int = 0
    targets_succeeded: int = 0
    targets_failed: int = 0
    targets_pending: int = 0
    scheduled_start: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    requested_by: str | None = None
    error_text: str | None = None


class CmResetPlanResponse(BaseModel):
    status: str = "success"
    job: CmResetJob


class CmResetJobListResponse(BaseModel):
    status: str = "success"
    jobs: list[CmResetJob] = Field(default_factory=list)


class CmResetJobDetailResponse(BaseModel):
    status: str = "success"
    job: CmResetJob


class CmResetJobActionResponse(BaseModel):
    status: str = "success"
    job: CmResetJob | None = None
    message: str | None = None


class CmResetTarget(BaseModel):
    id: int
    mac: str
    modem_ip: str | None = None
    cmts: str | None = None
    fiber_node: str | None = None
    state: str = "planned"
    error_text: str | None = None
    reset_at: str | None = None


class CmResetTargetListResponse(BaseModel):
    status: str = "success"
    targets: list[CmResetTarget] = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False


class CmResetCapabilitiesResponse(BaseModel):
    status: str = "success"
    scope_types: list[str] = Field(
        default_factory=lambda: ["single", "cmts", "fiber_node", "file"]
    )
    execution_window: dict[str, int] = Field(
        default_factory=lambda: {"start_hour": 1, "end_hour": 6}
    )
    max_concurrency: int = 10
    default_concurrency: int = 5
    confirmation_required: bool = True
