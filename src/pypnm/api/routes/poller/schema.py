# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
