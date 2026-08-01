from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopologyDatasetRow(BaseModel):
    file_date: str
    complete: bool
    topology_file: str | None = None
    modemlocation_file: str | None = None
    hierarchy_file: str | None = None
    topology_mtime: float | None = None
    modemlocation_mtime: float | None = None
    hierarchy_mtime: float | None = None


class TopologyDatasetsResponse(BaseModel):
    status: str = "success"
    volume_dir: str
    datasets: list[TopologyDatasetRow] = Field(default_factory=list)
    available_pair_dates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TopologyImportResponse(BaseModel):
    status: str = "success"
    snapshot_date: str
    imported: bool
    reason: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)


class TopologyPathsByModemsRequest(BaseModel):
    mac_addresses: list[str] = Field(default_factory=list)
    date: str | None = None
    max_hops: int = Field(default=32, ge=1, le=64)


class TopologySummaryResponse(BaseModel):
    status: str = "success"
    files: dict[str, Any]
    stats: dict[str, Any]
    topology_nodes: list[dict[str, Any]] = Field(default_factory=list)
    topology_edges: list[dict[str, Any]] = Field(default_factory=list)
    modems: list[dict[str, Any]] = Field(default_factory=list)


class ImportJobStatusResponse(BaseModel):
    status: str = "success"
    snapshot_date: str
    state: str               # queued | running | done | error
    stage: str = ""
    pct: int = 0
    stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str = ""
    finished_at: str | None = None
