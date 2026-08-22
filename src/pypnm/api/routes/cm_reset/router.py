# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from pypnm.api.routes.cm_reset.schema import (
    CmResetCapabilitiesResponse,
    CmResetJob,
    CmResetJobActionResponse,
    CmResetJobDetailResponse,
    CmResetJobListResponse,
    CmResetJobStartRequest,
    CmResetPlanRequest,
    CmResetPlanResponse,
    CmResetTargetListResponse,
)
from pypnm.api.routes.cm_reset.service import cm_reset_service
from pypnm.api.routes.cm_reset.worker import cm_reset_worker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/cm-reset", tags=["CM bulk reset"])

_CONFIRMATION_PASSPHRASE = "have you tried turning it on and off again?"
_GODMODE_PASSPHRASE = "its always dns"


@router.get("/capabilities", response_model=CmResetCapabilitiesResponse)
def get_capabilities() -> CmResetCapabilitiesResponse:
    return CmResetCapabilitiesResponse()


@router.get("/options/cmts")
def get_cmts_options(limit: int = Query(default=5000, ge=1, le=10000)) -> dict:
    try:
        options = cm_reset_service.get_cmts_options()
        return {"status": "success", "cmts": options[:limit]}
    except Exception as exc:
        logger.error("CM reset CMTS options failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/options/fiber-nodes")
def get_fiber_node_options(
    cmts: str = Query(max_length=128),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    try:
        options = cm_reset_service.get_fiber_node_options(cmts)
        return {"status": "success", "fiber_nodes": options[:limit]}
    except Exception as exc:
        logger.error("CM reset fiber-node options failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/jobs", response_model=CmResetJobListResponse)
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> CmResetJobListResponse:
    try:
        jobs = cm_reset_service.list_jobs(limit=limit)
        return CmResetJobListResponse(jobs=[CmResetJob(**j) for j in jobs])
    except Exception as exc:
        logger.error("CM reset job list failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.post("/jobs/plan", response_model=CmResetPlanResponse)
def create_plan(payload: CmResetPlanRequest) -> CmResetPlanResponse:
    try:
        job = cm_reset_service.create_plan(payload.model_dump())
        return CmResetPlanResponse(job=CmResetJob(**job))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("CM reset plan creation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Plan creation failed") from exc


@router.get("/jobs/{public_id}", response_model=CmResetJobDetailResponse)
def get_job(public_id: str) -> CmResetJobDetailResponse:
    try:
        job = cm_reset_service.get_job(public_id)
        return CmResetJobDetailResponse(job=CmResetJob(**job))
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as exc:
        logger.error("CM reset job detail failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.post("/jobs/{public_id}/start", response_model=CmResetJobActionResponse)
async def start_job(public_id: str, payload: CmResetJobStartRequest) -> CmResetJobActionResponse:
    # Validate confirmation passphrase
    if payload.confirmation_passphrase.strip().lower() != _CONFIRMATION_PASSPHRASE:
        raise HTTPException(
            status_code=403,
            detail="Incorrect confirmation passphrase. "
            "Please type: have you tried turning it on and off again?",
        )

    # Godmode: bypass execution window
    godmode = (
        payload.godmode_passphrase is not None
        and payload.godmode_passphrase.strip().lower() == _GODMODE_PASSPHRASE
    )

    try:
        job = await cm_reset_worker.start(
            public_id, max_concurrency=payload.max_concurrency, skip_window_check=godmode
        )
        msg = "Job started (GODMODE — window bypassed)" if godmode else "Job started"
        return CmResetJobActionResponse(job=CmResetJob(**job), message=msg)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("CM reset start failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to start job") from exc


@router.post("/jobs/{public_id}/cancel", response_model=CmResetJobActionResponse)
async def cancel_job(public_id: str) -> CmResetJobActionResponse:
    try:
        job = await cm_reset_worker.cancel(public_id)
        return CmResetJobActionResponse(job=CmResetJob(**job), message="Cancellation requested")
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as exc:
        logger.error("CM reset cancel failed: %s", exc)
        raise HTTPException(status_code=503, detail="Cancel failed") from exc


@router.delete("/jobs/{public_id}", response_model=CmResetJobActionResponse)
def delete_job(public_id: str) -> CmResetJobActionResponse:
    try:
        cm_reset_service.delete_job(public_id)
        return CmResetJobActionResponse(message=f"Job {public_id} deleted")
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("CM reset delete failed: %s", exc)
        raise HTTPException(status_code=503, detail="Delete failed") from exc


@router.get("/jobs/{public_id}/targets", response_model=CmResetTargetListResponse)
def list_targets(
    public_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    state: str | None = Query(default=None, max_length=24),
) -> CmResetTargetListResponse:
    try:
        page = cm_reset_service.list_targets(
            public_id, cursor=cursor, limit=limit, state=state
        )
        return CmResetTargetListResponse(**page)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as exc:
        logger.error("CM reset target list failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
