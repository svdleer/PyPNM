# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from pypnm.api.routes.rxmer_analytics.schema import (
    RxMerAggregateResponse,
    RxMerJob,
    RxMerJobActionResponse,
    RxMerJobListResponse,
    RxMerJobStartRequest,
    RxMerPlanRequest,
    RxMerPlanResponse,
    RxMerTargetListResponse,
)
from pypnm.api.routes.rxmer_analytics.service import rxmer_analytics_service
from pypnm.api.routes.rxmer_analytics.worker import rxmer_collection_worker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/rxmer-analytics", tags=["RxMER analytics"])


@router.get("/capabilities")
def get_capabilities() -> dict:
    return {"status": "success", **rxmer_analytics_service.capabilities()}


@router.post("/jobs/plan", response_model=RxMerPlanResponse, status_code=status.HTTP_201_CREATED)
def plan_job(payload: RxMerPlanRequest) -> RxMerPlanResponse:
    """Snapshot persisted inventory into a non-executing RxMER collection plan."""
    try:
        job, reused = rxmer_analytics_service.create_plan(payload.model_dump(mode="json"))
        return RxMerPlanResponse(status="success", job=RxMerJob(**job), reused=reused)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("RxMER plan creation failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics database unavailable") from exc


@router.get("/jobs", response_model=RxMerJobListResponse)
def list_jobs(limit: int = Query(default=30, ge=1, le=500)) -> RxMerJobListResponse:
    try:
        jobs = [RxMerJob(**row) for row in rxmer_analytics_service.list_jobs(limit)]
        return RxMerJobListResponse(status="success", jobs=jobs)
    except Exception as exc:
        logger.error("RxMER job listing failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics database unavailable") from exc


@router.get("/jobs/{public_id}", response_model=RxMerPlanResponse)
def get_job(public_id: str) -> RxMerPlanResponse:
    try:
        job = rxmer_analytics_service.get_job(public_id)
    except Exception as exc:
        logger.error("RxMER job lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics database unavailable") from exc
    if not job:
        raise HTTPException(status_code=404, detail="RxMER analytics job not found")
    return RxMerPlanResponse(status="success", job=RxMerJob(**job), reused=False)


@router.get("/jobs/{public_id}/modems", response_model=RxMerTargetListResponse)
def list_job_modems(
    public_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> RxMerTargetListResponse:
    try:
        page = rxmer_analytics_service.list_targets(public_id, cursor=cursor, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RxMER analytics job not found") from exc
    except Exception as exc:
        logger.error("RxMER target listing failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics database unavailable") from exc
    return RxMerTargetListResponse(status="success", **page)


@router.get("/jobs/{public_id}/aggregates", response_model=RxMerAggregateResponse)
def get_job_aggregates(
    public_id: str,
    bucket_db: float = Query(default=0.5, ge=0.25, le=5.0),
    cmts: str | None = Query(default=None, max_length=128),
    fiber_node: str | None = Query(default=None, max_length=128),
) -> RxMerAggregateResponse:
    try:
        payload = rxmer_analytics_service.aggregate_histograms(
            public_id,
            bucket_db=bucket_db,
            cmts=cmts,
            fiber_node=fiber_node,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RxMER analytics job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("RxMER aggregate lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics database unavailable") from exc
    return RxMerAggregateResponse(status="success", **payload)


@router.post("/jobs/{public_id}/start", response_model=RxMerJobActionResponse)
async def start_job(
    public_id: str,
    payload: RxMerJobStartRequest,
) -> RxMerJobActionResponse:
    try:
        job = await rxmer_collection_worker.start(
            public_id,
            max_concurrency=payload.max_concurrency,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RxMER analytics job not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("RxMER job start failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics worker unavailable") from exc
    return RxMerJobActionResponse(
        status="success",
        job=RxMerJob(**job),
        message="RxMER collection queued",
    )


@router.post("/jobs/{public_id}/cancel", response_model=RxMerJobActionResponse)
async def cancel_job(public_id: str) -> RxMerJobActionResponse:
    try:
        job = await rxmer_collection_worker.cancel(public_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RxMER analytics job not found") from exc
    except Exception as exc:
        logger.error("RxMER job cancellation failed: %s", exc)
        raise HTTPException(status_code=503, detail="RxMER analytics worker unavailable") from exc
    return RxMerJobActionResponse(
        status="success",
        job=RxMerJob(**job),
        message="Cancellation requested",
    )
