from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from pypnm.api.routes.topology.schema import (
    ImportJobStatusResponse,
    TopologyDatasetsResponse,
    TopologyImportResponse,
    TopologySummaryResponse,
)
from pypnm.api.routes.topology.service import topology_service

router = APIRouter(prefix="/api/topology", tags=["topology"])


@router.get("/datasets", response_model=TopologyDatasetsResponse)
def list_topology_datasets() -> TopologyDatasetsResponse:
    inventory = topology_service.scan_inventory()
    return TopologyDatasetsResponse(
        status="success",
        volume_dir=inventory.get("volume_dir") or "",
        datasets=inventory.get("datasets") or [],
        available_pair_dates=inventory.get("available_pair_dates") or [],
        warnings=inventory.get("warnings") or [],
    )


@router.post("/import", response_model=ImportJobStatusResponse)
def import_topology_dataset(
    selected_date: str | None = Query(default=None, alias="date"),
    force: bool = Query(default=False),
) -> ImportJobStatusResponse:
    """Start a background import and return immediately with initial job status."""
    try:
        job = topology_service.start_import_background(selected_date=selected_date, force=force)
        d = job.as_dict()
        return ImportJobStatusResponse(
            status="success",
            snapshot_date=d["snapshot_date"],
            state=d["state"],
            stage=d["stage"],
            pct=d["pct"],
            stats=d["stats"],
            error=d["error"],
            started_at=d["started_at"],
            finished_at=d["finished_at"],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/import/status", response_model=ImportJobStatusResponse)
def import_topology_status(
    selected_date: str = Query(alias="date"),
) -> ImportJobStatusResponse:
    """Poll current status of a running or completed background import job."""
    job = topology_service.get_import_job(selected_date)
    if not job:
        raise HTTPException(status_code=404, detail=f"No import job found for date {selected_date}")
    d = job.as_dict()
    return ImportJobStatusResponse(
        status="success",
        snapshot_date=d["snapshot_date"],
        state=d["state"],
        stage=d["stage"],
        pct=d["pct"],
        stats=d["stats"],
        error=d["error"],
        started_at=d["started_at"],
        finished_at=d["finished_at"],
    )


@router.get("/summary", response_model=TopologySummaryResponse)
def topology_summary(
    selected_date: str | None = Query(default=None, alias="date"),
    sample_limit: int = Query(default=200, ge=1, le=5000),
    auto_import: bool = Query(default=False),
) -> TopologySummaryResponse:
    try:
        payload = topology_service.get_summary(
            selected_date=selected_date,
            sample_limit=sample_limit,
            auto_import=auto_import,
        )
        return TopologySummaryResponse(
            status="success",
            files=payload.get("files") or {},
            stats=payload.get("stats") or {},
            topology_nodes=payload.get("topology_nodes") or [],
            topology_edges=payload.get("topology_edges") or [],
            modems=payload.get("modems") or [],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search/suggest")
def topology_search_suggest(
    selected_date: str | None = Query(default=None, alias="date"),
    search_type: str = Query(..., alias="type"),
    q: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    st = (search_type or "").strip().lower()
    if st not in {"fibernode", "postal_house", "customer_id"}:
        raise HTTPException(status_code=400, detail="type must be fibernode, postal_house, or customer_id")
    try:
        payload = topology_service.suggest_values(
            selected_date=selected_date,
            search_type=st,
            query=q,
            limit=limit,
        )
        return {"status": "success", **payload}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search/modems")
def topology_search_modems(
    selected_date: str | None = Query(default=None, alias="date"),
    search_type: str = Query(..., alias="type"),
    value: str = Query(default=""),
    house_number: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
) -> dict:
    st = (search_type or "").strip().lower()
    vv = (value or "").strip()
    if st not in {"fibernode", "postal_house", "customer_id"}:
        raise HTTPException(status_code=400, detail="type must be fibernode, postal_house, or customer_id")
    if st == "postal_house":
        if not vv or not (house_number or "").strip():
            raise HTTPException(status_code=400, detail="postal_house search requires value=<postalcode> and house_number")
    elif not vv:
        raise HTTPException(status_code=400, detail="value is required")

    try:
        payload = topology_service.search_modems(
            selected_date=selected_date,
            search_type=st,
            value=vv,
            house_number=house_number,
            limit=limit,
        )
        return {"status": "success", **payload}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/assets/{filename}")
def topology_asset(filename: str) -> FileResponse:
    try:
        path = topology_service.resolve_asset_path(filename)
        return FileResponse(path=str(path), filename=path.name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
