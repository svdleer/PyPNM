from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager
from pypnm.api.routes.cm_reset_single.schema import (
    CmSingleResetRequest,
    CmSingleResetResponse,
)
from pypnm.api.routes.cm_reset_single.service import cm_single_reset_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cm-reset", tags=["CM single reset"])

_CONFIRMATION_LETTERS = {"y", "e", "s"}
_DOCS_DEV_RESET_NOW_OID = "1.3.6.1.2.1.69.1.1.3.0"


@router.post("/single", response_model=CmSingleResetResponse)
async def reset_single_modem(payload: CmSingleResetRequest) -> CmSingleResetResponse:
    """Immediately reset one modem through its connected CM agent.

    This endpoint deliberately does not create a bulk-reset job and does not
    apply the bulk maintenance-window policy. The GUI authentication boundary
    and three-letter confirmation protect access to this operation.
    """
    clicks = [str(letter).strip().lower() for letter in payload.confirmation_clicks]
    if len(clicks) != 3 or len(set(clicks)) != 3 or set(clicks) != _CONFIRMATION_LETTERS:
        raise HTTPException(status_code=403, detail="Click Y, E, and S to confirm the modem reset")

    try:
        modem = cm_single_reset_service.resolve_modem(payload.mac)
    except Exception as exc:
        logger.error("Single CM reset inventory lookup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Modem inventory unavailable") from exc

    if not modem:
        raise HTTPException(status_code=404, detail="Modem not found in active inventory")

    target_ip = str(modem.get("ip") or "").strip()
    if not target_ip:
        raise HTTPException(status_code=422, detail="Modem has no IP address in inventory")

    agent_manager = get_agent_manager()
    agent_id = (
        agent_manager.get_agent_id_for_capability("cm_reachable", priority="interactive")
        if agent_manager else None
    )
    agent = agent_manager.get_agent(agent_id) if agent_manager and agent_id else None
    if not agent_manager or not agent:
        raise HTTPException(status_code=503, detail="No cm_reachable agent connected")

    try:
        task_id = await agent_manager.send_task(
            agent.agent_id,
            "snmp_set",
            {
                "target_ip": target_ip,
                "oid": _DOCS_DEV_RESET_NOW_OID,
                "value": 1,
                "type": "i",
                "target_role": "cm",
                "timeout": 3,
                "retries": 0,
            },
            timeout=10,
            priority="interactive",
        )
        result = await agent_manager.wait_for_task_async(task_id, timeout=8)
    except Exception as exc:
        logger.error("Single CM reset agent task failed for %s: %s", payload.mac, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="CM reset agent task failed") from exc

    if not result:
        raise HTTPException(status_code=504, detail="CM reset agent did not respond")
    if result.get("type") == "error":
        raise HTTPException(status_code=502, detail=result.get("error") or "CM reset agent rejected request")

    operation = result.get("result") or result
    if not operation.get("success"):
        raise HTTPException(status_code=502, detail=operation.get("error") or "CM reset SNMP SET failed")

    logger.info("Single CM reset sent for %s via %s", payload.mac, agent.agent_id)
    return CmSingleResetResponse(
        mac=str(modem.get("mac") or payload.mac),
        target_ip=target_ip,
        message=f"Reset command sent to modem {payload.mac}",
    )
