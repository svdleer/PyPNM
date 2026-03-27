# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from fastapi import APIRouter, Query

from pypnm.api.routes.poller.schema import (
    PollerJobsResponse,
    PollerRunRequest,
    PollerSchedulerPollRequest,
    PollerSchedulerStatusResponse,
    PollerSchedulerToggleRequest,
    PollerSettingUpsertRequest,
    PollerSettingsResponse,
    PollerSnapshotsAnalyticsResponse,
    PollerSnapshotsByDayResponse,
)
from pypnm.api.routes.poller.service import poller_service

router = APIRouter(prefix="/api/admin", tags=["poller"])


@router.get("/poller-settings", response_model=PollerSettingsResponse)
def list_poller_settings() -> PollerSettingsResponse:
    return PollerSettingsResponse(status="success", pollers=poller_service.list_pollers())


@router.post("/poller-settings")
def upsert_poller_setting(payload: PollerSettingUpsertRequest) -> dict:
    poller_id = poller_service.upsert_poller(payload.model_dump(exclude_none=True))
    return {"status": "success", "poller_id": poller_id}


@router.post("/poller-settings/{poller_id}/run")
def run_poller_setting(poller_id: int, payload: PollerRunRequest) -> dict:
    job_id = poller_service.enqueue_run(poller_id=poller_id, source=payload.source)
    return {"status": "success", "job_id": job_id}


@router.get("/poller-jobs", response_model=PollerJobsResponse)
def list_poller_jobs(limit: int = Query(default=30, ge=1, le=500)) -> PollerJobsResponse:
    jobs = poller_service.list_jobs(limit=limit)
    return PollerJobsResponse(status="success", jobs=jobs)


@router.post("/poller-jobs/clear")
def clear_poller_jobs() -> dict:
    deleted = poller_service.clear_jobs()
    return {"status": "success", "deleted": deleted}


@router.post("/poller-jobs/clear-all")
def clear_all_poller_jobs() -> dict:
    deleted = poller_service.clear_all_jobs()
    return {"status": "success", "deleted": deleted}


@router.post("/poller-jobs/{job_id}/kill")
def kill_poller_job(job_id: int) -> dict:
    out = poller_service.kill_job(job_id=job_id)
    return {"status": "success", **out}


@router.get("/inventory/modems")
def list_inventory_modems(
    cmts: str | None = None,
    search_type: str | None = None,
    search_value: str | None = None,
    interface: str | None = None,
    limit: int = Query(default=10000, ge=1, le=50000),
) -> dict:
    modems = poller_service.list_inventory_modems(
        cmts=cmts,
        search_type=search_type,
        search_value=search_value,
        interface_filter=interface,
        limit=limit,
    )
    return {"status": "success", "modems": modems, "count": len(modems), "source": "pypnm-inventory"}


@router.get("/inventory/modems/{mac_address}")
def get_inventory_modem(mac_address: str) -> dict:
    modem = poller_service.get_inventory_modem_by_mac(mac_address)
    if not modem:
        return {"status": "error", "message": "Modem not found"}
    return {"status": "success", "modem": modem, "source": "pypnm-inventory"}


@router.get("/poller-scheduler/status", response_model=PollerSchedulerStatusResponse)
def poller_scheduler_status() -> PollerSchedulerStatusResponse:
    scheduler = poller_service.get_scheduler_status()
    return PollerSchedulerStatusResponse(status="success", scheduler=scheduler)


@router.post("/poller-scheduler/toggle")
def toggle_poller_scheduler(payload: PollerSchedulerToggleRequest) -> dict:
    scheduler = poller_service.set_scheduler_enabled(enabled=payload.enabled)
    return {"status": "success", "scheduler": scheduler}


@router.post("/poller-scheduler/poll")
def set_poller_scheduler_poll(payload: PollerSchedulerPollRequest) -> dict:
    scheduler = poller_service.set_scheduler_poll(poll_sec=payload.poll_sec)
    return {"status": "success", "scheduler": scheduler}


@router.post("/poller-scheduler/run-once")
def run_poller_scheduler_once() -> dict:
    queued = poller_service.run_scheduler_once()
    return {"status": "success", "queued": queued}


@router.post("/poller-scheduler/decisions/clear")
def clear_poller_scheduler_decisions() -> dict:
    deleted = poller_service.clear_scheduler_decisions()
    return {"status": "success", "deleted": deleted}


@router.get("/poller-snapshots/by-day", response_model=PollerSnapshotsByDayResponse)
def poller_snapshots_by_day(
    lookback_days: int = Query(default=14, ge=1, le=365),
    limit: int = Query(default=300, ge=1, le=5000),
) -> PollerSnapshotsByDayResponse:
    rows = poller_service.snapshots_by_day(lookback_days=lookback_days, limit=limit)
    return PollerSnapshotsByDayResponse(status="success", rows=rows)


@router.get("/poller-snapshots/analytics", response_model=PollerSnapshotsAnalyticsResponse)
def poller_snapshots_analytics(
    lookback_days: int = Query(default=14, ge=1, le=365),
) -> PollerSnapshotsAnalyticsResponse:
    analytics = poller_service.snapshots_analytics(lookback_days=lookback_days)
    return PollerSnapshotsAnalyticsResponse(status="success", analytics=analytics)


# ── Modem refresh (on-demand single-modem enrichment) ──────────


@router.post("/modem-refresh")
def enqueue_modem_refresh(payload: dict) -> dict:
    mac = payload.get("mac", "")
    cmts = payload.get("cmts")
    if not mac:
        return {"status": "error", "message": "mac is required"}
    req_id = poller_service.enqueue_modem_refresh(
        mac=mac, cmts=cmts, requested_by=payload.get("requested_by"),
    )
    return {"status": "success", "request_id": req_id}


@router.get("/modem-refresh/{mac}/status")
def get_modem_refresh_status(mac: str) -> dict:
    result = poller_service.get_refresh_status(mac)
    if not result:
        return {"status": "success", "refresh": None}
    return {"status": "success", "refresh": result}


@router.post("/modem-refresh/{req_id}/cancel")
def cancel_modem_refresh(req_id: int) -> dict:
    poller_service.cancel_refresh_request(req_id)
    return {"status": "success", "cancelled": True}


# ── Enrichment progress ──────────────────────────────────────


@router.get("/inventory/enrichment-progress")
def get_enrichment_progress(cmts: str | None = None) -> dict:
    progress = poller_service.get_enrichment_progress(cmts=cmts)
    return {"status": "success", **progress}


# ── Queue heads (admin dashboard) ────────────────────────────


@router.get("/queue-head")
def get_queue_heads() -> dict:
    heads = poller_service.get_queue_heads()
    return {"status": "success", **heads}
