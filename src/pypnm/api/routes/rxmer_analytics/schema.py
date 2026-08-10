# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RxMerScopeType(str, Enum):
    ALL_NETWORK = "all_network"
    CMTS = "cmts"


class RxMerScope(BaseModel):
    type: RxMerScopeType = RxMerScopeType.ALL_NETWORK
    cmts: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_selection(self) -> "RxMerScope":
        normalized = sorted({value.strip() for value in self.cmts if value.strip()})
        if self.type == RxMerScopeType.CMTS and not normalized:
            raise ValueError("cmts scope requires at least one CMTS")
        if self.type == RxMerScopeType.ALL_NETWORK and normalized:
            raise ValueError("all_network scope cannot include CMTS selections")
        self.cmts = normalized
        return self


class RxMerPlanRequest(BaseModel):
    scope: RxMerScope = Field(default_factory=RxMerScope)
    online_only: bool = True
    requested_by: str = Field(default="api", min_length=1, max_length=64)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    raw_retention_days: int = Field(default=7, ge=1, le=365)
    aggregate_retention_days: int = Field(default=90, ge=1, le=3650)


class RxMerJob(BaseModel):
    public_id: str
    trigger_type: str
    status: str
    scope: dict[str, Any]
    scope_hash: str
    inventory_revision: str | None = None
    targets_total: int = 0
    targets_running: int = 0
    targets_succeeded: int = 0
    targets_partial: int = 0
    targets_failed: int = 0
    channels_succeeded: int = 0
    channels_failed: int = 0
    requested_by: str | None = None
    error_text: str | None = None
    raw_retention_days: int = 7
    aggregate_retention_days: int = 90
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RxMerPlanResponse(BaseModel):
    status: str = "success"
    job: RxMerJob
    reused: bool = False


class RxMerJobListResponse(BaseModel):
    status: str = "success"
    jobs: list[RxMerJob] = Field(default_factory=list)


class RxMerTarget(BaseModel):
    id: int
    mac: str
    modem_ip: str
    cmts: str
    cmts_ip: str | None = None
    fiber_node: str | None = None
    inventory_snapshot_id: str | None = None
    state: str
    expected_channels: int = 0
    completed_channels: int = 0
    failed_channels: int = 0
    attempt_count: int = 0
    error_class: str | None = None
    error_text: str | None = None
    completeness: str | None = None
    valid_channel_count: int | None = None
    sample_count: int | None = None
    avg_db: float | None = None
    best_db: float | None = None
    best_channel_id: int | None = None
    best_subcarrier_index: int | None = None
    best_frequency_hz: int | None = None
    created_at: datetime
    updated_at: datetime


class RxMerTargetListResponse(BaseModel):
    status: str = "success"
    targets: list[RxMerTarget] = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False


class RxMerAggregateBin(BaseModel):
    rxmer_db: float
    modem_count: int


class RxMerAggregateResponse(BaseModel):
    status: str = "success"
    job_public_id: str
    total_modems: int = 0
    completeness: dict[str, int] = Field(default_factory=dict)
    average_rxmer: list[RxMerAggregateBin] = Field(default_factory=list)
    best_subcarrier_rxmer: list[RxMerAggregateBin] = Field(default_factory=list)
    bucket_db: float


class RxMerSpectrumPoint(BaseModel):
    frequency_hz: int
    average_db: float | None = None
    max_db: float | None = None
    worst_db: float | None = None
    sample_count: int


class RxMerChannelSpan(BaseModel):
    channel_id: int
    start_frequency_hz: int
    end_frequency_hz: int
    spacing_hz: int
    modem_count: int


class RxMerSpectrumResponse(BaseModel):
    status: str = "success"
    job_public_id: str
    state: str
    message: str | None = None
    source_revision: int = 0
    source_channels: int = 0
    source_modems: int = 0
    source_samples: int = 0
    frequency_start_hz: int | None = None
    frequency_end_hz: int | None = None
    bin_width_hz: int | None = None
    points: list[RxMerSpectrumPoint] = Field(default_factory=list, max_length=4000)
    channel_spans: list[RxMerChannelSpan] = Field(default_factory=list, max_length=64)
    span_groups_omitted: int = 0


class RxMerSpectrumBuildResponse(BaseModel):
    status: str = "success"
    job_public_id: str
    state: str
    queued: bool = False
    message: str | None = None


class RxMerJobStartRequest(BaseModel):
    max_concurrency: int = Field(default=10, ge=1, le=20)


class RxMerJobActionResponse(BaseModel):
    status: str = "success"
    job: RxMerJob
    message: str | None = None


class RxMerDeleteResponse(BaseModel):
    status: str = "success"
    job_public_id: str
    message: str
