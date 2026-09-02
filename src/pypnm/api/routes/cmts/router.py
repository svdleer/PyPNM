# SPDX-License-Identifier: Apache-2.0
# CMTS Discovery API Routes

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import secrets
from inspect import signature

from fastapi import APIRouter, Header, HTTPException, Query

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager
from pypnm.api.routes.cmts.schemas import (
    CMTSModemInterfaceRequest,
    CMTSModemInterfaceResponse,
    CMTSModemRequest,
    CMTSModemResponse,
    CMTSRemoteQueryProbeRequest,
    CMTSRemoteQueryProbeResponse,
    CPECollectionRequest,
    CPECollectionResponse,
)
from pypnm.api.routes.cmts.service import CMTSModemService, cancel_enrichment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmts", tags=["CMTS Discovery"])
_remote_query_probe_lock = asyncio.Lock()


def _remote_query_probe_target_allowed(cmts_ip: str) -> bool:
    """Authorize a probe only for an operator-configured CMTS address."""
    raw = (
        os.environ.get("PYPNM_REMOTE_QUERY_PROBE_TARGETS")
        or os.environ.get("POLLER_CMTS_TARGETS")
        or ""
    ).strip()
    if not raw:
        return False
    try:
        requested = str(ipaddress.ip_address(cmts_ip.strip()))
    except ValueError:
        return False
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        parsed = [item.strip() for item in raw.replace("\n", ",").split(",")]
    if not isinstance(parsed, list):
        return False
    for item in parsed:
        candidate = item
        if isinstance(item, dict):
            candidate = item.get("ip") or item.get("cmts_ip") or item.get("IPAddress")
        try:
            if candidate and str(ipaddress.ip_address(str(candidate).strip())) == requested:
                return True
        except ValueError:
            continue
    return False


# Ensure agent manager is initialized
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)


@router.get("/modems", response_model=CMTSModemResponse)
async def get_cmts_modems(
    cmts_ip: str,
    community: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50000),
    enrich: bool = False,
    refresh: bool = False,
    collect_cpe: bool = False,
    modem_community: str | None = None,
    cmts_hostname: str = "",
    agent_priority: str = "interactive",
) -> CMTSModemResponse:
    """
    **CMTS Modem Discovery**

    Discover all cable modems registered on a CMTS via SNMP bulk walk.

    The request is routed to an available PyPNM agent which performs
    bounded SNMP walks of the DOCSIS modem registration tables.

    **Returns for each modem:**
    - MAC address, IP address, registration status
    - DOCSIS version (1.0, 1.1, 2.0, 3.0, 3.1)
    - Upstream interface and channel information
    - Partial service state (D3.1)
    - Vendor from MAC OUI lookup
    - ofdma_enabled / ofdm_enabled flags

    **Optional enrichment** (enrich=true):
    - Model name from modem sysDescr
    - Software/firmware version from modem sysDescr

    **Performance:**
    - Base discovery: ~3 seconds for 1000+ modems
    - With enrichment: ~30-60 seconds (queries each modem)
    """
    logger.info(f"CMTS modem discovery request: {cmts_ip} (enrich={enrich})")

    service = CMTSModemService(agent_priority=agent_priority)

    if limit is None:
        raw = os.environ.get("CM_MODEM_LIMIT", "50000")
        try:
            limit = max(1, min(int(raw), 50000))
        except (TypeError, ValueError):
            limit = 50000

    try:
        discovery_kwargs = {
            'cmts_ip': cmts_ip,
            'community': community,
            'limit': limit,
            'enrich': enrich,
            'collect_cpe': collect_cpe,
            'modem_community': modem_community,
            'cmts_hostname': cmts_hostname or '',
        }
        if 'refresh' in signature(service.discover_modems).parameters:
            discovery_kwargs['refresh'] = refresh
        elif refresh:
            return CMTSModemResponse(
                success=False,
                modems=[],
                count=0,
                error='This PyPNM service version does not support forced inventory refresh',
            )
        result = await service.discover_modems(**discovery_kwargs)
        
        if not result.get('success'):
            return CMTSModemResponse(
                success=False,
                modems=[],
                count=0,
                error=result.get('error', 'Discovery failed')
            )
        
        modems = result.get('modems', [])
        enriched = result.get('enriched', False)
        
        return CMTSModemResponse(
            success=True,
            modems=modems,
            count=len(modems),
            enriched=enriched,
            capability_enriched=result.get('capability_enriched') is True,
            cached=result.get('cached', False),
            enriching=result.get('enriching', False),
            complete=result.get('complete', False),
            truncated=result.get('truncated', False),
            inventory_stale=result.get('inventory_stale') is True,
            inventory_complete=result.get(
                'inventory_complete', result.get('complete')
            ) is True,
            source=result.get('source'),
            requested_limit=result.get('requested_limit'),
            collected_at=result.get('collected_at'),
            revision_at=result.get('revision_at'),
            snapshot_id=result.get('snapshot_id'),
            critical_oid_errors=result.get('critical_oid_errors') or {},
            raw_legacy_mac_count=result.get('raw_legacy_mac_count'),
            raw_d3_mac_count=result.get('raw_d3_mac_count'),
            cpe_addresses=result.get('cpe_addresses') or [],
            skipped_cpe_rows=int(result.get('skipped_cpe_rows') or 0),
            cpe_complete=result.get('cpe_complete') is True,
            cpe_truncated=result.get('cpe_truncated') is True,
            cpe_oid_errors=result.get('cpe_oid_errors') or {},
            enrichment_progress=result.get('enrich_progress'),
        )
        
    except Exception as e:
        logger.exception(f"Error in CMTS modem discovery: {e}")
        return CMTSModemResponse(
            success=False,
            modems=[],
            count=0,
            error=str(e)
        )


@router.post("/modems/query", response_model=CMTSModemResponse)
async def query_cmts_modems(payload: CMTSModemRequest) -> CMTSModemResponse:
    """Discover CMTS modems without placing SNMP credentials in the URL."""
    return await get_cmts_modems(
        cmts_ip=payload.cmts_ip,
        community=payload.community,
        limit=payload.limit,
        enrich=payload.enrich,
        refresh=payload.refresh,
        collect_cpe=payload.collect_cpe,
        modem_community=payload.modem_community,
        cmts_hostname=payload.cmts_hostname,
        agent_priority=payload.agent_priority,
    )


@router.post("/modem-interface/query", response_model=CMTSModemInterfaceResponse)
async def query_modem_interface(
    payload: CMTSModemInterfaceRequest,
) -> CMTSModemInterfaceResponse:
    """Resolve cable-interface and Fiber Node values for one inventory modem."""
    agent_manager = get_agent_manager()
    if not agent_manager or not agent_manager.get_available_agents():
        raise HTTPException(status_code=503, detail="No agents available")
    try:
        result = await CMTSModemService().resolve_modem_interface(
            cmts_ip=payload.cmts_ip,
            docsif3_index=payload.docsif3_index,
            community=payload.community,
            modem_ip=payload.modem_ip,
        )
        return CMTSModemInterfaceResponse(**result)
    except Exception as exc:
        logger.exception(
            "Targeted CMTS interface lookup failed for %s index %s: %s",
            payload.cmts_ip,
            payload.docsif3_index,
            exc,
        )
        return CMTSModemInterfaceResponse(success=False, error=str(exc))


@router.post("/cpe/query", response_model=CPECollectionResponse)
async def query_cpe_addresses(payload: CPECollectionRequest) -> CPECollectionResponse:
    """Collect a fresh, validated CPE-address generation from one CMTS."""
    agent_manager = get_agent_manager()
    if not agent_manager or not agent_manager.get_available_agents():
        raise HTTPException(status_code=503, detail="No agents available")
    try:
        result = await CMTSModemService(
            agent_priority=payload.agent_priority
        ).collect_cpe_addresses(
            cmts_ip=payload.cmts_ip,
            community=payload.community,
            limit=payload.limit,
            overall_timeout_sec=payload.overall_timeout_sec,
            agent_command_timeout_sec=payload.agent_command_timeout_sec,
            min_remaining_tree_reserve_sec=(
                payload.min_remaining_tree_reserve_sec
            ),
        )
        return CPECollectionResponse(**result)
    except Exception as exc:
        logger.exception("CPE collection failed for %s: %s", payload.cmts_ip, exc)
        return CPECollectionResponse(
            success=False,
            cpe_addresses=[],
            count=0,
            error=str(exc),
        )


@router.post(
    "/remote-query/probe",
    response_model=CMTSRemoteQueryProbeResponse,
)
async def probe_remote_query_identity(
    payload: CMTSRemoteQueryProbeRequest,
    probe_token: str | None = Header(
        default=None,
        alias="X-PyPNM-Probe-Token",
        include_in_schema=False,
    ),
) -> CMTSRemoteQueryProbeResponse:
    """Probe fixed CMTS remote-query identity OIDs without persistence or fallback."""
    expected_token = os.environ.get("PYPNM_REMOTE_QUERY_PROBE_TOKEN") or ""
    if not expected_token:
        raise HTTPException(status_code=503, detail="Remote-query probe disabled")
    if not probe_token or not secrets.compare_digest(probe_token, expected_token):
        raise HTTPException(status_code=403, detail="Probe authorization failed")
    if not _remote_query_probe_target_allowed(payload.cmts_ip):
        raise HTTPException(status_code=404, detail="CMTS target not found")

    agent_manager = get_agent_manager()
    if not agent_manager or not agent_manager.get_available_agents():
        raise HTTPException(status_code=503, detail="No agents available")
    if _remote_query_probe_lock.locked():
        raise HTTPException(status_code=429, detail="A remote-query probe is already running")
    try:
        async with _remote_query_probe_lock:
            result = await CMTSModemService(
                agent_priority="bulk",
            ).probe_remote_query_identity(
                cmts_ip=str(ipaddress.ip_address(payload.cmts_ip.strip())),
                provider=payload.provider,
                limit=payload.limit,
                sample_limit=payload.sample_limit,
            )
        return CMTSRemoteQueryProbeResponse(**result)
    except Exception:
        logger.exception("CMTS remote-query probe failed")
        return CMTSRemoteQueryProbeResponse(
            success=False,
            remote_query_provider=payload.provider,
            freshness_available=payload.provider == "cadant",
            error_code="internal_error",
        )


@router.post("/enrich/cancel")
async def cancel_enrich(cmts_ip: str):
    """Cancel an in-progress background enrichment for the given CMTS."""
    cancelled = cancel_enrichment(cmts_ip)
    return {"status": "cancelled" if cancelled else "not_running", "cmts_ip": cmts_ip}
