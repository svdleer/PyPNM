# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from pypnm.api.routes.cm_snmp_query.schema import (
    OidEntry,
    SnmpQueryCapabilitiesResponse,
    SnmpQueryJob,
    SnmpQueryJobActionResponse,
    SnmpQueryJobDetailResponse,
    SnmpQueryJobListResponse,
    SnmpQueryJobStartRequest,
    SnmpQueryPlanRequest,
    SnmpQueryPlanResponse,
    SnmpQueryTargetListResponse,
    SnmpTemplate,
    SnmpTemplateCreateRequest,
    SnmpTemplateListResponse,
)
from pypnm.api.routes.cm_snmp_query.service import cm_snmp_query_service
from pypnm.api.routes.cm_snmp_query.worker import cm_snmp_query_worker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/custom-snmp", tags=["Custom SNMP query"])


# ── Capabilities ─────────────────────────────────────────────

@router.get("/capabilities", response_model=SnmpQueryCapabilitiesResponse)
def get_capabilities() -> SnmpQueryCapabilitiesResponse:
    return SnmpQueryCapabilitiesResponse()


# ── Options ──────────────────────────────────────────────────

@router.get("/options/cmts")
def get_cmts_options(limit: int = Query(default=5000, ge=1, le=10000)) -> dict:
    try:
        return {"status": "success", "cmts": cm_snmp_query_service.get_cmts_options()[:limit]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/options/fiber-nodes")
def get_fiber_node_options(
    cmts: str = Query(max_length=128),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    try:
        return {"status": "success", "fiber_nodes": cm_snmp_query_service.get_fiber_node_options(cmts)[:limit]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


# ── Templates ────────────────────────────────────────────────

@router.get("/templates", response_model=SnmpTemplateListResponse)
def list_templates() -> SnmpTemplateListResponse:
    try:
        templates = cm_snmp_query_service.list_templates()
        return SnmpTemplateListResponse(templates=[SnmpTemplate(**t) for t in templates])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.post("/templates", response_model=SnmpTemplate)
def create_template(payload: SnmpTemplateCreateRequest) -> SnmpTemplate:
    try:
        tmpl = cm_snmp_query_service.create_template(
            payload.name,
            payload.description,
            [e.model_dump() for e in payload.oids],
        )
        return SnmpTemplate(**tmpl)
    except Exception as exc:
        logger.error("Template creation failed: %s", exc)
        raise HTTPException(status_code=503, detail="Template creation failed") from exc


@router.delete("/templates/{template_id}")
def delete_template(template_id: int) -> dict:
    try:
        cm_snmp_query_service.delete_template(template_id)
        return {"status": "success"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Template not found")


# ── Jobs ─────────────────────────────────────────────────────

@router.get("/jobs", response_model=SnmpQueryJobListResponse)
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> SnmpQueryJobListResponse:
    try:
        jobs = cm_snmp_query_service.list_jobs(limit=limit)
        return SnmpQueryJobListResponse(jobs=[SnmpQueryJob(**j) for j in jobs])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.post("/jobs/plan", response_model=SnmpQueryPlanResponse)
def create_plan(payload: SnmpQueryPlanRequest) -> SnmpQueryPlanResponse:
    try:
        oids_dicts = [e.model_dump() for e in payload.oids] if payload.oids else []
        job = cm_snmp_query_service.create_plan({
            "scope": payload.scope,
            "oids": oids_dicts,
            "max_modems": payload.max_modems,
            "template_id": payload.template_id,
            "requested_by": payload.requested_by,
        })
        return SnmpQueryPlanResponse(job=SnmpQueryJob(**job))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("SNMP query plan failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Plan creation failed") from exc


@router.get("/jobs/{public_id}", response_model=SnmpQueryJobDetailResponse)
def get_job(public_id: str) -> SnmpQueryJobDetailResponse:
    try:
        job = cm_snmp_query_service.get_job(public_id)
        return SnmpQueryJobDetailResponse(job=SnmpQueryJob(**job))
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")


@router.post("/jobs/{public_id}/start", response_model=SnmpQueryJobActionResponse)
async def start_job(public_id: str, payload: SnmpQueryJobStartRequest) -> SnmpQueryJobActionResponse:
    try:
        job = await cm_snmp_query_worker.start(public_id, max_concurrency=payload.max_concurrency)
        return SnmpQueryJobActionResponse(job=SnmpQueryJob(**job), message="Job started")
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("SNMP query start failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to start job") from exc


@router.post("/jobs/{public_id}/cancel", response_model=SnmpQueryJobActionResponse)
async def cancel_job(public_id: str) -> SnmpQueryJobActionResponse:
    try:
        job = await cm_snmp_query_worker.cancel(public_id)
        return SnmpQueryJobActionResponse(job=SnmpQueryJob(**job), message="Cancellation requested")
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")


@router.delete("/jobs/{public_id}")
def delete_job(public_id: str) -> dict:
    try:
        cm_snmp_query_service.delete_job(public_id)
        return {"status": "success", "deleted": public_id}
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/jobs/{public_id}/targets", response_model=SnmpQueryTargetListResponse)
def list_targets(
    public_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> SnmpQueryTargetListResponse:
    try:
        page = cm_snmp_query_service.list_targets(public_id, cursor=cursor, limit=limit)
        return SnmpQueryTargetListResponse(**page)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")


@router.get("/jobs/{public_id}/report")
def download_report(
    public_id: str,
    format: str = Query(default="csv", pattern="^(json|csv)$"),
) -> StreamingResponse:
    try:
        stream = cm_snmp_query_service.stream_report(public_id, report_format=format)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except Exception as exc:
        logger.error("SNMP query report failed: %s", exc)
        raise HTTPException(status_code=503, detail="Report unavailable") from exc
    media_type = "application/json" if format == "json" else "text/csv; charset=utf-8"
    filename = f"custom-snmp-{public_id[:8]}.{format}"
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/verify-oid")
async def verify_oid(payload: dict) -> dict:
    """Test an OID against a sample modem to verify it returns data.

    POST body: {"oid": "sysUpTime.0", "cmts": "CMTS-NAME"}
    Returns: {"success": true, "oid": "...", "numeric_oid": "1.3.6...", "value": "12345", "modem_ip": "10.x.x.x"}
    """
    import os
    from pypnm.api.routes.cm_snmp_query.oid_resolver import resolve_oid

    oid_raw = str(payload.get("oid") or "").strip()
    cmts = str(payload.get("cmts") or "").strip()
    if not oid_raw:
        raise HTTPException(status_code=400, detail="oid is required")

    # Resolve MIB name to numeric OID server-side
    oid = resolve_oid(oid_raw)

    # Find a sample online modem to test against
    cm_snmp_query_service.ensure_schema()
    if cmts:
        modems = cm_snmp_query_service._query(
            "SELECT ip FROM modem_inventory_current "
            "WHERE cmts=%s AND ip IS NOT NULL AND TRIM(ip)<>'' "
            "AND status IN ('operational','registrationComplete','ipComplete','online') "
            "ORDER BY RAND() LIMIT 1",
            (cmts,),
        )
    else:
        modems = cm_snmp_query_service._query(
            "SELECT ip FROM modem_inventory_current "
            "WHERE ip IS NOT NULL AND TRIM(ip)<>'' "
            "AND status IN ('operational','registrationComplete','ipComplete','online') "
            "ORDER BY RAND() LIMIT 1",
        )

    if not modems:
        raise HTTPException(status_code=404, detail="No online modem found to test against")

    modem_ip = modems[0]["ip"]

    # Send SNMP GET via cm-agent
    from pypnm.api.agent.manager import get_agent_manager
    from pypnm.config.pnm_config_manager import PnmConfigManager

    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")

    agent = (
        agent_manager.get_agent_for_capability("cm_reachable")
        or agent_manager.get_agent_for_capability("snmp_get")
    )
    if not agent:
        raise HTTPException(status_code=503, detail="No cm-agent connected")

    community = (
        os.environ.get("MODEM_COMMUNITY")
        or os.environ.get("CM_SNMP_COMMUNITY")
        or str(PnmConfigManager.get_write_community())
    )

    import asyncio
    task_id = await agent_manager.send_task(
        agent.agent_id,
        "snmp_get",
        {"target_ip": modem_ip, "oid": oid, "community": community, "timeout": 5, "retries": 1},
        timeout=15,
        priority="interactive",
    )
    result = await agent_manager.wait_for_task_async(task_id, timeout=15)

    if not result or result.get("type") != "response":
        return {"success": False, "oid": oid_raw, "numeric_oid": oid, "error": "Agent timeout", "modem_ip": modem_ip}

    res_data = result.get("result", {})
    if not res_data.get("success"):
        return {"success": False, "oid": oid_raw, "numeric_oid": oid, "error": res_data.get("error", "SNMP GET failed"), "modem_ip": modem_ip}

    # Parse the value
    output = str(res_data.get("output") or "")
    if " = " in output:
        value = output.split(" = ", 1)[1].strip()
    else:
        value = output.strip() or None

    if not value or value.lower() in ("no such object", "no such instance", ""):
        return {"success": False, "oid": oid_raw, "numeric_oid": oid, "error": f"OID not found on modem ({value or 'empty'})", "modem_ip": modem_ip}

    return {"success": True, "oid": oid_raw, "numeric_oid": oid, "value": value, "modem_ip": modem_ip}
