from __future__ import annotations

from typing import Any, Literal

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


class TopologyModemsByMacsRequest(BaseModel):
    mac_addresses: list[str] = Field(min_length=1, max_length=5000)
    date: str | None = None


class PhysicalFiberNodeReconcileRequest(BaseModel):
    date: str = Field(min_length=1)
    expected_mac_addresses: list[str] = Field(min_length=1, max_length=5000)
    anchor_mac_address: str = Field(min_length=1)
    refresh: Literal[False] = False


class TopologyFiberNodeScanTargetsRequest(BaseModel):
    """Resolve one exact technical topology FiberNode into current scan targets."""

    date: str | None = None
    fiber_node: str = Field(min_length=1, max_length=128)
    anchor_mac_address: str = Field(min_length=1)
    refresh: Literal[False] = False


class PhysicalFiberNodeTarget(BaseModel):
    anchor_mac_address: str
    cmts: str
    cmts_ip: str
    physical_fiber_node: str


class PhysicalFiberNodeInventoryQuality(BaseModel):
    source: str
    snapshot_id: str | None = None
    collected_at: str | None = None
    revision_at: str | None = None
    complete: bool = False
    truncated: bool = False
    authoritative: bool = False
    stale: bool = False
    quarantined: bool = False


class PhysicalFiberNodeReconcileRecord(BaseModel):
    mac_address: str
    expected: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    classification: Literal[
        "expected_current_member",
        "expected_moved",
        "expected_not_current",
        "expected_location_unknown",
    ]
    selectable: bool
    disabled_reason: str | None = None


class PhysicalFiberNodeReconcileResponse(BaseModel):
    status: str = "success"
    snapshot_date: str
    topology_fiber_node: str | None = None
    target: PhysicalFiberNodeTarget
    inventory: PhysicalFiberNodeInventoryQuality
    count: int
    records: list[PhysicalFiberNodeReconcileRecord] = Field(default_factory=list)


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
