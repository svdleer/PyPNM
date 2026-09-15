# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from pypnm.api.routes.cm_snmp_query.schema import (
    OidEntry,
    SnmpOidVerifyRequest,
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
from pypnm.api.routes.cm_snmp_query.service import (
    CmtsDirectoryUnavailableError,
    cm_snmp_query_service,
)
from pypnm.api.routes.poller.service import poller_service
from pypnm.api.routes.cm_snmp_query.worker import cm_snmp_query_worker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/custom-snmp", tags=["Custom SNMP query"])


# ── Capabilities ─────────────────────────────────────────────

@router.get("/capabilities", response_model=SnmpQueryCapabilitiesResponse)
def get_capabilities() -> SnmpQueryCapabilitiesResponse:
    return SnmpQueryCapabilitiesResponse()


# ── Options ──────────────────────────────────────────────────

@router.get("/options/cmts")
def get_cmts_options(
    affiliate: str = Query(default="all", pattern="^(all|vfz|fziggo|fupc)$"),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    try:
        return {
            "status": "success",
            "cmts": cm_snmp_query_service.get_cmts_options(affiliate)[:limit],
            "aggregate": {
                "kind": "affiliate_all",
                "modem_count": poller_service.get_inventory_modem_total(area=affiliate),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CmtsDirectoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail="CMTS directory unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/options/fiber-nodes")
def get_fiber_node_options(
    cmts: str = Query(max_length=128),
    affiliate: str = Query(default="all", pattern="^(all|vfz|fziggo|fupc)$"),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    try:
        fiber_nodes = cm_snmp_query_service.get_fiber_node_options(cmts, affiliate)
        return {"status": "success", "fiber_nodes": fiber_nodes[:limit]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CmtsDirectoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail="CMTS directory unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/options/modem-vendors")
def get_modem_vendor_options(
    affiliate: str = Query(default="all", pattern="^(all|vfz|fziggo|fupc)$"),
    cmts: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    try:
        return {
            "status": "success",
            "modem_vendors": poller_service.get_inventory_modem_facet_options(
                dimension="vendor", area=affiliate, cmts=cmts, limit=limit
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Inventory summary unavailable") from exc


@router.get("/options/modem-types")
def get_modem_type_options(
    affiliate: str = Query(default="all", pattern="^(all|vfz|fziggo|fupc)$"),
    cmts: str | None = Query(default=None, max_length=128),
    modem_vendor: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    try:
        return {
            "status": "success",
            "modem_types": poller_service.get_inventory_modem_facet_options(
                dimension="model",
                area=affiliate,
                cmts=cmts,
                modem_vendor=modem_vendor,
                limit=limit,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Inventory summary unavailable") from exc


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
async def create_plan(payload: SnmpQueryPlanRequest) -> SnmpQueryPlanResponse:
    try:
        oids_dicts = [e.model_dump() for e in payload.oids] if payload.oids else []
        job = cm_snmp_query_service.create_plan({
            "scope": payload.scope,
            "oids": oids_dicts,
            "verification_receipts": payload.verification_receipts,
            "max_modems": payload.max_modems,
            "all_matching_modems": payload.all_matching_modems,
            "template_id": payload.template_id,
            "requested_by": payload.requested_by,
        })
        if payload.all_matching_modems:
            import asyncio

            asyncio.create_task(
                asyncio.to_thread(
                    cm_snmp_query_service.materialize_all_matching_plan,
                    job["public_id"],
                ),
                name=f"snmp-plan-{job['public_id']}",
            )
        return SnmpQueryPlanResponse(job=SnmpQueryJob(**job))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CmtsDirectoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail="CMTS directory unavailable") from exc
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
        job = await cm_snmp_query_worker.start(
            public_id,
            max_concurrency=payload.max_concurrency,
            community=payload.community,
        )
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
async def verify_oid(payload: SnmpOidVerifyRequest) -> dict:
    """Verify an OID against bounded CM or CMTS candidates via configured agents."""
    import asyncio

    from pypnm.api.agent.manager import get_agent_manager
    from pypnm.api.routes.cm_snmp_query.oid_resolver import resolve_oid

    oid_raw = payload.oid.strip()
    if not oid_raw:
        raise HTTPException(status_code=400, detail="oid is required")
    oid = resolve_oid(oid_raw)
    selected_cmts = (payload.cmts or "").strip() or None

    try:
        cmts_candidates = await asyncio.to_thread(
            cm_snmp_query_service.get_verify_cmts_candidates,
            affiliate=payload.affiliate,
            cmts=selected_cmts,
            limit=1 if selected_cmts else 3,
        )
        if not cmts_candidates:
            raise HTTPException(status_code=404, detail="No eligible CMTS verification target found")

        attempts: list[dict[str, object]] = []
        if payload.target_mode == "cmts":
            candidates = [
                {
                    "role": "cmts",
                    "ip": cmts["ip_address"],
                    "cmts": cmts["hostname"],
                    "cmts_ip": cmts["ip_address"],
                    "mac": None,
                }
                for cmts in cmts_candidates
            ]
        else:
            candidates = []
            modem_limit = 3 if selected_cmts else 1
            for cmts in cmts_candidates:
                modems = await asyncio.to_thread(
                    cm_snmp_query_service.get_verify_modem_candidates,
                    cmts=cmts["hostname"],
                    modem_vendor=payload.modem_vendor,
                    modem_type=payload.modem_type,
                    limit=modem_limit,
                )
                candidates.extend(
                    {
                        "role": "cm",
                        "ip": modem["ip"],
                        "cmts": modem["cmts"],
                        "cmts_ip": modem["cmts_ip"],
                        "mac": modem["mac"],
                    }
                    for modem in modems
                )
        if not candidates:
            raise HTTPException(status_code=404, detail="No eligible modem verification target found")

        agent_manager = get_agent_manager()
        if not agent_manager:
            raise HTTPException(status_code=503, detail="Agent manager not available")
        capability = "cm_reachable" if payload.target_mode == "modem" else "cmts_reachable"

        for target in candidates:
            attempt = {
                "role": target["role"],
                "ip": target["ip"],
                "cmts": target["cmts"],
                "cmts_ip": target["cmts_ip"],
                "mac": target["mac"],
            }
            try:
                agent_id = agent_manager.get_agent_id_for_capability(
                    capability, priority="interactive"
                )
                if not agent_id:
                    raise RuntimeError(
                        f"No {capability} agent with interactive capacity"
                    )
                task_id = await agent_manager.send_task(
                    agent_id,
                    "snmp_get",
                    {
                        "target_ip": target["ip"],
                        "oid": oid,
                        "target_role": target["role"],
                        "timeout": 3,
                        "retries": 0,
                    },
                    timeout=5,
                    priority="interactive",
                )
                result = await agent_manager.wait_for_task_async(task_id, timeout=5)
                response = result.get("result") if isinstance(result, dict) else None
                if not isinstance(response, dict):
                    error = (
                        result.get("error")
                        if isinstance(result, dict)
                        else "Agent returned an invalid task response"
                    )
                    raise RuntimeError(str(error or "Agent task failed"))

                output = str(response.get("output") or "")
                value = output.split(" = ", 1)[1].strip() if " = " in output else output.strip()
                if response.get("success") and value and value.lower() not in {
                    "no such object",
                    "no such instance",
                }:
                    attempt["success"] = True
                    attempts.append(attempt)
                    modem_ip = target["ip"] if target["role"] == "cm" else None
                    return {
                        "success": True,
                        "oid": oid_raw,
                        "numeric_oid": oid,
                        "value": value,
                        "target_mode": payload.target_mode,
                        "modem_ip": modem_ip,
                        "cmts_ip": target["cmts_ip"],
                        "target": {**attempt, "modem_ip": modem_ip},
                        "verification_receipt": cm_snmp_query_service.issue_verification_receipt(
                            numeric_oid=oid,
                            target_mode=payload.target_mode,
                            affiliate=payload.affiliate,
                            cmts=selected_cmts,
                            modem_vendor=payload.modem_vendor,
                            modem_type=payload.modem_type,
                        ),
                        "attempts_used": len(attempts),
                        "attempts_limit": len(candidates),
                        "attempts": attempts,
                    }
                error = response.get("error")
                if not error and value:
                    error = f"OID returned no usable value ({value})"
                raise RuntimeError(str(error or "OID returned no value"))
            except Exception as exc:
                attempt["success"] = False
                attempt["error"] = str(exc)
            attempts.append(attempt)

        first_target = candidates[0]
        return {
            "success": False,
            "oid": oid_raw,
            "numeric_oid": oid,
            "target_mode": payload.target_mode,
            "modem_ip": first_target["ip"] if first_target["role"] == "cm" else None,
            "cmts_ip": first_target["cmts_ip"],
            "error": "OID verification failed for all selected candidates",
            "attempts_used": len(attempts),
            "attempts_limit": len(candidates),
            "attempts": attempts,
        }
    except HTTPException:
        raise
    except CmtsDirectoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail="CMTS directory unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("OID verification candidate selection failed")
        raise HTTPException(status_code=503, detail="OID verification unavailable") from exc


@router.get("/mib-search")
def mib_search(q: str = Query(default="", max_length=64), limit: int = Query(default=20, ge=1, le=50)) -> dict:
    """Search known MIB object names for autocomplete."""
    from pypnm.api.routes.cm_snmp_query.mib_catalog import search_catalog
    results = search_catalog(q, limit=limit)
    return {"status": "success", "results": results}


@router.delete("/jobs")
def delete_all_jobs() -> dict:
    """Delete all non-running custom SNMP jobs."""
    try:
        cm_snmp_query_service.ensure_schema()
        rows = cm_snmp_query_service._query(
            "SELECT id FROM snmp_query_job WHERE status != 'running'"
        )
        count = 0
        for row in rows:
            job_id = int(row["id"])
            cm_snmp_query_service._execute("DELETE FROM snmp_query_target WHERE job_id=%s", (job_id,))
            cm_snmp_query_service._execute("DELETE FROM snmp_query_job WHERE id=%s", (job_id,))
            count += 1
        return {"status": "success", "deleted": count}
    except Exception as exc:
        logger.error("Delete all SNMP jobs failed: %s", exc)
        raise HTTPException(status_code=503, detail="Delete failed") from exc
