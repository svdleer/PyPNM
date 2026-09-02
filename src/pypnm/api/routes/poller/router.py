# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

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


@router.post("/poller-settings/{poller_id}/enabled")
def set_poller_setting_enabled(
    poller_id: int,
    payload: PollerSchedulerToggleRequest,
) -> dict:
    out = poller_service.set_poller_enabled(poller_id, payload.enabled)
    if out.get("state") == "not_found":
        raise HTTPException(status_code=404, detail="Poller not found")
    return {"status": "success", **out}


@router.post("/poller-settings/{poller_id}/run")
def run_poller_setting(poller_id: int, payload: PollerRunRequest) -> dict:
    out = poller_service.request_run(poller_id=poller_id, source=payload.source)
    state = out.get("state")
    if state == "not_found":
        raise HTTPException(status_code=404, detail="Poller not found")
    if state == "disabled":
        raise HTTPException(status_code=409, detail="Poller is disabled")
    if state == "outside_run_window":
        detail = out.get("detail")
        message = "Poller is outside its configured run window"
        if detail:
            message = f"{message} ({detail})"
        raise HTTPException(status_code=409, detail=message)
    if state == "rejected":
        raise HTTPException(status_code=409, detail="Poller run could not be queued")
    return {"status": "success", **out}


@router.delete("/poller-settings/{poller_id}")
def delete_poller_setting(poller_id: int) -> dict:
    out = poller_service.delete_poller(poller_id=poller_id)
    if out.get("state") == "not_found":
        raise HTTPException(status_code=404, detail="Poller not found")
    if out.get("state") == "active_jobs":
        raise HTTPException(status_code=409, detail="Poller has active jobs")
    if out.get("state") == "protected":
        raise HTTPException(
            status_code=409,
            detail="System task can be disabled but not deleted",
        )
    return {"status": "success", **out}


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
    limit: int | None = Query(default=None, ge=1, le=50000),
) -> dict:
    if limit is None:
        limit = poller_service._cm_modem_limit_default()

    try:
        modems = poller_service.list_inventory_modems(
            cmts=cmts,
            search_type=search_type,
            search_value=search_value,
            interface_filter=interface,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"inventory/modems DB error: {exc}")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    snapshot = poller_service.get_inventory_snapshot(cmts) if cmts else None
    response = {
        "status": "success",
        "modems": modems,
        "count": len(modems),
        "source": "pypnm-inventory",
    }
    if snapshot:
        response.update({
            "complete": snapshot.get("complete") is True,
            "truncated": snapshot.get("truncated") is True,
            "requested_limit": snapshot.get("requested_limit"),
            "row_count": snapshot.get("row_count"),
            "snapshot_id": snapshot.get("snapshot_id"),
            "collected_at": snapshot.get("collected_at"),
            "revision_at": snapshot.get("revision_at"),
            "inventory_source": snapshot.get("source"),
            "capability_enriched": snapshot.get("capability_enriched") is True,
            "critical_oid_errors": snapshot.get("critical_oid_errors") or {},
            "raw_legacy_mac_count": snapshot.get("raw_legacy_mac_count"),
            "raw_d3_mac_count": snapshot.get("raw_d3_mac_count"),
        })
    return response


@router.get("/inventory/snapshots/current")
def list_current_inventory_snapshots() -> dict:
    """Return small cache-revision records without loading modem rows."""
    try:
        snapshots = poller_service.list_inventory_snapshots()
    except Exception as exc:
        logger.error("inventory/snapshots/current DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "success", "snapshots": snapshots}


@router.get("/inventory/cpe/index")
def list_cpe_index(limit: int = Query(default=500000, ge=1, le=500000)) -> dict:
    """Return a complete CPE address index for GUI Redis warming."""
    try:
        result = poller_service.list_cpe_index(limit=limit)
    except Exception as exc:
        logger.error("inventory/cpe/index DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if result.get('truncated') is True:
        raise HTTPException(status_code=409, detail="CPE index exceeds transfer limit")
    return {"status": "success", **result}


@router.get("/inventory/cpe/suggestions")
def suggest_cpe_addresses(
    q: str = Query(min_length=1, max_length=45),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    try:
        suggestions = poller_service.suggest_cpe_addresses(q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("inventory/cpe/suggestions DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "success", "suggestions": suggestions}


@router.get("/inventory/summary")
def inventory_summary(
    cmts: str | None = None,
    top_n: int = Query(default=25, ge=1, le=100),
) -> dict:
    """Return vendor/model/firmware/DOCSIS count breakdowns for the inventory dashboard."""
    try:
        data = poller_service.get_inventory_summary(cmts=cmts, top_n=top_n)
    except Exception as exc:
        logger.error("inventory/summary DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "success", "source": "mysql", **data}


@router.get("/inventory/modems/{mac_address}")
def get_inventory_modem(mac_address: str) -> dict:
    try:
        modem = poller_service.get_inventory_modem_by_mac(mac_address)
    except Exception as exc:
        logger.error(f"inventory/modems/{mac_address} DB error: {exc}")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if not modem:
        return {"status": "error", "message": "Modem not found"}
    return {"status": "success", "modem": modem, "source": "pypnm-inventory"}


@router.post("/inventory/modems/bulk")
def get_inventory_modems_bulk(body: dict) -> dict:
    mac_addresses = body.get("mac_addresses") or []
    if not mac_addresses or not isinstance(mac_addresses, list):
        return {"status": "error", "message": "mac_addresses list required"}
    if len(mac_addresses) > 5000:
        return {"status": "error", "message": "max 5000 MACs per request"}
    try:
        modems = poller_service.get_inventory_modems_bulk(mac_addresses)
    except Exception as exc:
        logger.error(f"inventory/modems/bulk DB error: {exc}")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "success", "modems": modems, "count": len(modems)}


@router.post("/inventory/modems/clear")
def clear_inventory_modems(body: dict) -> dict:
    cmts = str(body.get("cmts") or "").strip()
    cmts_ip = str(body.get("cmts_ip") or "").strip()
    if not cmts and not cmts_ip:
        return {"status": "error", "message": "cmts or cmts_ip required"}

    try:
        deleted = poller_service.clear_inventory_modems(cmts=cmts or None, cmts_ip=cmts_ip or None)
    except Exception as exc:
        logger.error(f"inventory/modems/clear DB error: {exc}")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "status": "success",
        "deleted": deleted,
        "cmts": cmts,
        "cmts_ip": cmts_ip,
    }


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
