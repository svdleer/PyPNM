# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

from pypnm.api.routes.common.classes.common_endpoint_classes.schema.base_snmp import (
    SNMPConfig,
    SNMPv2c,
)
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.cm_snmp_operation import DocsPnmCmCtlStatus
from pypnm.docsis.data_type.ClabsDocsisVersion import ClabsDocsisVersion
from pypnm.docsis.data_type.InterfaceStats import DocsisIfType
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import InetAddressStr, MacAddressStr

PreCheckStatus = tuple[ServiceStatusCode, str]

# Check once at import time
_USE_AGENT = os.environ.get('PYPNM_USE_AGENT_SNMP', '').lower() == 'true'


class CableModemServicePreCheck:
    """
    Performs preliminary connectivity and validation checks against a DOCSIS Cable Modem.

    This service supports:
    - ICMP ping reachability check (via agent when PYPNM_USE_AGENT_SNMP=true)
    - SNMP reachability check (via agent when PYPNM_USE_AGENT_SNMP=true)
    - MAC address verification
    - Optional DOCSIS version compatibility validation
    - Optional validation that OFDM (DS) and/or OFDMA (US) channels exist

    Initialization methods:
    - Provide a pre-constructed `CableModem` object
    - Or specify a `mac_address` and `ip_address` pair
    """

    def __init__(
        self,
        cable_modem: CableModem | None = None,
        mac_address: MacAddressStr | None = None,
        ip_address: InetAddressStr | None = None,
        snmp_config: SNMPConfig | None = None,
        check_docsis_version: list[ClabsDocsisVersion] = None,
        validate_ofdm_exist: bool       = False,
        validate_ofdma_exist: bool      = False,
        validate_scqam_exist: bool      = False,
        validate_atdma_exist: bool      = False,
        validate_pnm_ready_status: bool = True,
        ignore_mac_address_check: bool  = False,
    ) -> None:
        if check_docsis_version is None:
            check_docsis_version = []
        self.logger = logging.getLogger(self.__class__.__name__)

        if cable_modem:
            self.cm = cable_modem
        elif mac_address and ip_address:

            if snmp_config is None:
                self.logger.debug("No SNMPConfig provided, using default settings")
                snmp_config = SNMPConfig(snmp_v2c=SNMPv2c(community=None))

            self.cm = CableModem(
                mac_address     =   MacAddress(mac_address),
                inet            =   Inet(ip_address),
                write_community =   snmp_config.snmp_v2c.community,
            )
        else:
            raise ValueError("Must provide either `cable_modem` or both `mac_address` and `ip_address`.")

        # Store SNMP community for agent-based operations
        self._snmp_community = (
            snmp_config.snmp_v2c.community if snmp_config and snmp_config.snmp_v2c and snmp_config.snmp_v2c.community
            else None
        )
        self._ip_address = ip_address or str(self.cm.get_inet_address)

        if check_docsis_version:
            if isinstance(check_docsis_version, ClabsDocsisVersion):
                self.check_docsis_version = [check_docsis_version]
            elif isinstance(check_docsis_version, Iterable):
                self.check_docsis_version = list(check_docsis_version)
            else:
                self.check_docsis_version = [check_docsis_version]
        else:
            self.check_docsis_version = []

        self._validate_ofdma_exist      = validate_ofdma_exist
        self._validate_ofdm_exist       = validate_ofdm_exist
        self._validate_scqam_exist      = validate_scqam_exist
        self._validate_atdma_exist      = validate_atdma_exist
        self._validate_pnm_ready_stat   = validate_pnm_ready_status
        self._ignore_mac_address_check  = ignore_mac_address_check

    # ------------------------------------------------------------------
    # Agent helpers
    # ------------------------------------------------------------------

    def _get_agent_manager(self):
        """Lazy import to avoid circular imports."""
        from pypnm.api.agent.manager import get_agent_manager
        return get_agent_manager()

    def _get_snmp_agent(self):
        """Return the first authenticated agent that has snmp_get capability."""
        mgr = self._get_agent_manager()
        if not mgr:
            return None, None
        agent = mgr.get_agent_for_capability('snmp_get')
        return mgr, agent

    # ------------------------------------------------------------------
    # Main pre-check
    # ------------------------------------------------------------------

    async def run_precheck(self) -> tuple[ServiceStatusCode, str]:
        """
        Run full pre-check routine:
          1. Ping modem  (via agent when available)
          2. Perform SNMP check (via agent when available)
          3. Does Mac Match CableModem Mac
          4. Validate DOCSIS version (optional)

        Returns:
            Tuple[ServiceStatusCode, str]: Status and message.
        """
        self.logger.debug(f"Starting pre-check for CableModem: {self.cm}")

        status = await self.ping_reachable()
        if status != ServiceStatusCode.SUCCESS:
            msg = f"Ping check failed: {status}"
            self.logger.error(msg)
            return status, msg

        status = await self.snmp_reachable()
        if status != ServiceStatusCode.SUCCESS:
            msg = f"SNMP check failed: {status}"
            self.logger.error(msg)
            return status, msg

        if not self._ignore_mac_address_check:
            status = await self.isMacCorrect()
            if status != ServiceStatusCode.SUCCESS:

                try:
                    mac = await self.getRealMacAddress()
                except Exception as e:
                    self.logger.error(f"Error retrieving real MAC address: {e}", exc_info=True)
                    mac = "Unknown"

                msg = f"Found: {mac} MAC address CableModem Mac check failed: {status}"
                self.logger.error(msg)
                return status, msg

        if self.check_docsis_version:
            status, msg = await self.validate_docsis_version()
            if status != ServiceStatusCode.SUCCESS:
                return status, msg

        if self._validate_ofdm_exist:
            status, msg = await self.validate_ofdm_channel_exist()
            if status != ServiceStatusCode.SUCCESS:
                return status, msg

        if self._validate_ofdma_exist:
            status, msg = await self.validate_ofdma_channel_exist()
            if status != ServiceStatusCode.SUCCESS:
                return status, msg

        if self._validate_scqam_exist:
            status, msg = await self.validate_scqam_channel_exist()
            if status != ServiceStatusCode.SUCCESS:
                return status, msg

        if self._validate_atdma_exist:
            status, msg = await self.validate_atdma_channel_exist()
            if status != ServiceStatusCode.SUCCESS:
                return status, msg

        if self._validate_pnm_ready_stat:
            status, msg = await self.validate_pnm_ready_status()
            if status != ServiceStatusCode.SUCCESS:
                return status, msg

        msg = "Pre-check successful: CableModem reachable via ping and SNMP"
        self.logger.debug(msg)
        return ServiceStatusCode.SUCCESS, msg

    # ------------------------------------------------------------------
    # Ping
    # ------------------------------------------------------------------

    async def ping_reachable(self) -> ServiceStatusCode:
        """
        Perform an ICMP ping test.
        When PYPNM_USE_AGENT_SNMP is set, the ping is executed by the remote
        agent (which actually has L3 access to the modem network).

        Returns:
            SUCCESS if reachable, else PING_FAILED.
        """
        if _USE_AGENT:
            return await self._ping_via_agent()
        return self._ping_local()

    def _ping_local(self) -> ServiceStatusCode:
        """Local ping (direct network access)."""
        try:
            if self.cm.is_ping_reachable():
                self.logger.debug("Ping check passed (local)")
                return ServiceStatusCode.SUCCESS
            self.logger.debug("Ping check failed (local)")
            return ServiceStatusCode.PING_FAILED
        except Exception as e:
            self.logger.error(f"Ping check exception: {e}", exc_info=True)
            return ServiceStatusCode.PING_FAILED

    async def _ping_via_agent(self) -> ServiceStatusCode:
        """Ping via pyPNMAgent over WebSocket."""
        try:
            mgr, agent = self._get_snmp_agent()
            if not mgr or not agent:
                self.logger.warning("No agent available for ping – falling back to local")
                return self._ping_local()

            task_id = await mgr.send_task(
                agent.agent_id,
                'ping',
                {'target': self._ip_address},
                timeout=5.0,
            )
            result = await mgr.wait_for_task_async(task_id, timeout=5.0)

            if result and result.get('type') == 'response':
                data = result.get('result', {})
                if data.get('reachable') or data.get('success'):
                    self.logger.debug("Ping check passed (agent)")
                    return ServiceStatusCode.SUCCESS

            self.logger.debug("Ping check failed (agent)")
            return ServiceStatusCode.PING_FAILED
        except Exception as e:
            self.logger.error(f"Ping via agent exception: {e}", exc_info=True)
            return ServiceStatusCode.PING_FAILED

    # ------------------------------------------------------------------
    # SNMP reachability
    # ------------------------------------------------------------------

    async def snmp_reachable(self) -> ServiceStatusCode:
        """
        Perform SNMP reachability check (sysDescr GET).
        When PYPNM_USE_AGENT_SNMP is set, the SNMP query is routed through
        the remote agent.

        Returns:
            SUCCESS if SNMP response received, else UNREACHABLE_SNMP.
        """
        if _USE_AGENT:
            return await self._snmp_via_agent()
        return await self._snmp_local()

    async def _snmp_local(self) -> ServiceStatusCode:
        """Direct SNMP sysDescr check."""
        try:
            if await self.cm.is_snmp_reachable():
                self.logger.debug("SNMP check passed (local)")
                return ServiceStatusCode.SUCCESS
            self.logger.debug("SNMP check failed (local)")
            return ServiceStatusCode.UNREACHABLE_SNMP
        except Exception as e:
            self.logger.error(f"SNMP check exception: {e}", exc_info=True)
            return ServiceStatusCode.UNREACHABLE_SNMP

    async def _snmp_via_agent(self) -> ServiceStatusCode:
        """SNMP sysDescr check via pyPNMAgent."""
        try:
            mgr, agent = self._get_snmp_agent()
            if not mgr or not agent:
                self.logger.warning("No agent available for SNMP – falling back to local")
                return await self._snmp_local()

            community = self._snmp_community or 'public'

            task_id = await mgr.send_task(
                agent.agent_id,
                'snmp_get',
                {
                    'target_ip': self._ip_address,
                    'oid': '1.3.6.1.2.1.1.1.0',       # sysDescr.0
                    'community': community,
                },
                timeout=5.0,
            )
            result = await mgr.wait_for_task_async(task_id, timeout=5.0)

            if result and result.get('type') == 'response':
                data = result.get('result', {})
                if data.get('success') and data.get('output'):
                    self.logger.debug(f"SNMP check passed (agent): {data['output'][:80]}")
                    return ServiceStatusCode.SUCCESS

            self.logger.debug(f"SNMP check failed (agent): {result}")
            return ServiceStatusCode.UNREACHABLE_SNMP
        except Exception as e:
            self.logger.error(f"SNMP via agent exception: {e}", exc_info=True)
            return ServiceStatusCode.UNREACHABLE_SNMP

    # ------------------------------------------------------------------
    # MAC address
    # ------------------------------------------------------------------

    async def isMacCorrect(self) -> ServiceStatusCode:
        """Check if the cable modem's MAC address is correct."""
        try:
            if await self.cm.isCableModemMacCorrect():
                self.logger.debug("MAC address check passed")
                return ServiceStatusCode.SUCCESS
            self.logger.debug("MAC address check failed")
            return ServiceStatusCode.CM_MAC_DOES_MATCH_MATCH
        except Exception as e:
            self.logger.error(f"MAC address check exception: {e}", exc_info=True)
            return ServiceStatusCode.UNREACHABLE_SNMP

    async def getRealMacAddress(self) -> MacAddress:
        """Retrieve the real MAC address from the cable modem via SNMP."""
        try:
            mac = await self.cm.getIfPhysAddress()
            self.logger.debug(f"Retrieved MAC address: {mac}")
            return mac
        except Exception as e:
            self.logger.error(f"Error retrieving MAC address: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # DOCSIS version
    # ------------------------------------------------------------------

    async def validate_docsis_version(self) -> tuple[ServiceStatusCode, str]:
        """Check if the modem's DOCSIS version is in the accepted list."""
        try:
            base_cap: ClabsDocsisVersion = await self.cm.getDocsisBaseCapability()
            if base_cap not in self.check_docsis_version:
                msg = f"Invalid DOCSIS Version: {base_cap.name}"
                self.logger.error(msg)
                return ServiceStatusCode.INVALID_DOCSIS_VERSION, msg

            self.logger.debug(f"DOCSIS version check passed: {base_cap.name}")
            return ServiceStatusCode.SUCCESS, "Valid DOCSIS version"

        except Exception as e:
            msg = f"Error checking DOCSIS version: {e}"
            self.logger.error(msg, exc_info=True)
            return ServiceStatusCode.INVALID_DOCSIS_VERSION, msg

    # ------------------------------------------------------------------
    # Channel existence checks
    # ------------------------------------------------------------------

    async def validate_ofdm_channel_exist(self) -> tuple[ServiceStatusCode, str]:
        """Check whether any OFDM downstream channels exist."""
        idx_chan_stack = await self.cm.getDocsIf31CmDsOfdmChannelIdIndexStack()
        if not idx_chan_stack:
            msg = "No OFDM channels found on the cable modem."
            return ServiceStatusCode.NO_OFDMA_CHANNELS_EXIST, msg
        return ServiceStatusCode.SUCCESS, "OFDM downstream channels detected."

    async def validate_ofdma_channel_exist(self) -> tuple[ServiceStatusCode, str]:
        """Check whether any OFDMA upstream channels exist."""
        idx_chan_stack = await self.cm.getDocsIf31CmUsOfdmaChannelIdIndexStack()
        if not idx_chan_stack:
            msg = "No OFDMA channels found on the cable modem."
            return ServiceStatusCode.NO_OFDMA_CHANNELS_EXIST, msg
        return ServiceStatusCode.SUCCESS, "OFDMA upstream channels detected."

    async def validate_scqam_channel_exist(self) -> tuple[ServiceStatusCode, str]:
        """Check whether any SC-QAM downstream channels exist."""
        scqam_idx_list = await self.cm.getIfTypeIndex(DocsisIfType.docsCableDownstream)
        if not scqam_idx_list:
            msg = "No SC-QAM channels found on the cable modem."
            return ServiceStatusCode.NO_SCQAM_CHAN_ID_INDEX_FOUND, msg
        return ServiceStatusCode.SUCCESS, "SC-QAM downstream channels detected."

    async def validate_atdma_channel_exist(self) -> tuple[ServiceStatusCode, str]:
        """Check whether any ATDMA upstream channels exist."""
        atdma_idx_list = await self.cm.getIfTypeIndex(DocsisIfType.docsCableUpstream)
        if not atdma_idx_list:
            msg = "No ATDMA channels found on the cable modem."
            return ServiceStatusCode.NO_ATDMA_CHAN_ID_INDEX_FOUND, msg
        return ServiceStatusCode.SUCCESS, "ATDMA upstream channels detected."

    async def validate_pnm_ready_status(self) -> PreCheckStatus:
        out: PreCheckStatus = (ServiceStatusCode.SUCCESS, DocsPnmCmCtlStatus.READY.name)
        rst: DocsPnmCmCtlStatus = await self.cm.getDocsPnmCmCtlStatus()
        if rst != DocsPnmCmCtlStatus.READY:
            return ServiceStatusCode.SUCCESS, rst.name
        return out
