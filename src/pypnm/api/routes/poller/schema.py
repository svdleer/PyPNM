# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PollerSettingUpsertRequest(BaseModel):
    id: Optional[int] = Field(default=None)
    name: str = Field(default="default")
    enabled: bool = Field(default=True)
    scope_type: str = Field(default="all_cmts")
    scope_json: Optional[str] = Field(default=None)
    collect_identity: bool = Field(
        default=False,
        description="Deprecated no-op; direct modem identity collection is disabled",
    )
    collect_scqam: bool = Field(default=True)
    collect_rxmer: bool = Field(default=True)
    interval_minutes: int = Field(default=360)
    run_window_start: Optional[str] = Field(default=None)
    run_window_end: Optional[str] = Field(default=None)
    max_concurrency: int = Field(default=1)
    max_agent_queue_depth: int = Field(default=20)
    retention_days: int = Field(default=30)
    heavy_window_start: Optional[str] = Field(default="00:30")
    heavy_window_end: Optional[str] = Field(default="05:30")
    heavy_max_modems: int = Field(default=300)
    heavy_delay_ms: int = Field(default=0)
    max_runtime_sec: int = Field(default=14400)


class PollerRunRequest(BaseModel):
    source: Optional[str] = Field(default="api")


class PollerSchedulerToggleRequest(BaseModel):
    enabled: bool = Field(default=True)


class PollerSchedulerPollRequest(BaseModel):
    poll_sec: int = Field(default=60)


class ModemRefreshRequest(BaseModel):
    mac: str
    cmts: Optional[str] = Field(default=None)


class InventoryMySQLBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=128)
    page_size: int = Field(default=1000, ge=100, le=5000)


class InventoryMySQLBackfillAgent(BaseModel):
    agent_id: str
    bulk_free_slots: int = Field(ge=0)


class InventoryMySQLBackfillAgentCollectionResponse(BaseModel):
    status: str = Field(default="success")
    agents: List[InventoryMySQLBackfillAgent] = Field(default_factory=list)


class InventoryMySQLBackfillJob(BaseModel):
    public_id: str
    status: str
    agent_id: str
    cursor: str = Field(default="")
    page_size: int
    source_total: Optional[int] = Field(default=None)
    percent: Optional[float] = Field(default=None)
    pages_received: int = Field(default=0)
    rows_received: int = Field(default=0)
    rows_matched: int = Field(default=0)
    rows_updated: int = Field(default=0)
    rows_skipped: int = Field(default=0)
    rows_unmatched: int = Field(default=0)
    rows_unchanged: int = Field(default=0)
    vendor_unmapped: int = Field(default=0)
    attempt_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    error_code: Optional[str] = Field(default=None)
    error_text: Optional[str] = Field(default=None)
    cancellation_requested: bool = Field(default=False)
    created_at: str
    started_at: Optional[str] = Field(default=None)
    last_attempt_at: Optional[str] = Field(default=None)
    next_attempt_at: Optional[str] = Field(default=None)
    cancel_requested_at: Optional[str] = Field(default=None)
    updated_at: str
    finished_at: Optional[str] = Field(default=None)


class InventoryMySQLBackfillResponse(BaseModel):
    status: str = Field(default="success")
    job: InventoryMySQLBackfillJob


class InventoryMySQLBackfillCollectionResponse(BaseModel):
    status: str = Field(default="success")
    jobs: List[InventoryMySQLBackfillJob] = Field(default_factory=list)


class PollerSettingsResponse(BaseModel):
    status: str = Field(default="success")
    pollers: List[Dict[str, Any]] = Field(default_factory=list)


class PollerJobsResponse(BaseModel):
    status: str = Field(default="success")
    jobs: List[Dict[str, Any]] = Field(default_factory=list)


class PollerSchedulerStatusResponse(BaseModel):
    status: str = Field(default="success")
    scheduler: Dict[str, Any] = Field(default_factory=dict)


class PollerSnapshotsByDayResponse(BaseModel):
    status: str = Field(default="success")
    rows: List[Dict[str, Any]] = Field(default_factory=list)


class PollerSnapshotsAnalyticsResponse(BaseModel):
    status: str = Field(default="success")
    analytics: Dict[str, Any] = Field(default_factory=dict)
