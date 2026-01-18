# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

from __future__ import annotations

import logging
from typing import cast

from pypnm.api.routes.common.extended.common_measure_service import CommonMeasureService
from pypnm.api.routes.common.extended.common_process_service import MessageResponse
from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.schemas import UsSpecAnCapturePara
from pypnm.config.pnm_config_manager import PnmConfigManager
from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.inet import Inet
from pypnm.lib.types import ChannelId
from pypnm.pnm.data_type.pnm_test_types import DocsPnmCmCtlTest


class CmUsSpectrumAnalysisService(CommonMeasureService):
    """
    Service For Cable Modem Upstream Spectrum Analysis (UTSC - Single Run)

    Purpose
    -------
    Orchestrates a single upstream spectrum analyzer measurement on a target cable modem,
    applying the provided capture parameters for UTSC (Upstream Triggered Spectrum Capture).
    This is the CMTS-based measurement for upstream spectrum analysis.

    Parameters
    ----------
    cable_modem : CableModem
        Target cable modem on which to run the measurement.
    tftp_servers : tuple[Inet, Inet], optional
        Primary/secondary TFTP server addresses used for result file storage.
    tftp_path : str, optional
        Remote TFTP directory where result files are written.
    capture_parameters : UsSpecAnCapturePara
        Upstream spectrum capture configuration.
    """

    def __init__(
        self,
        cable_modem: CableModem,
        tftp_servers: tuple[Inet, Inet] = PnmConfigManager.get_tftp_servers(),
        tftp_path: str = PnmConfigManager.get_tftp_path(),
        *,
        capture_parameters: UsSpecAnCapturePara,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        pnmCmCtlTest = DocsPnmCmCtlTest.SPECTRUM_ANALYZER

        super().__init__(
            pnmCmCtlTest,
            cable_modem,
            tftp_servers,
            tftp_path,
            cable_modem.getWriteCommunity(),
        )
        self.setSpectrumCaptureParameters(capture_parameters)


class UsOfdmaChanSpecAnalyzerService(CommonMeasureService):
    """Helper Service For OFDMA Upstream Spectrum Analyzer Runs"""

    def __init__(
        self,
        cable_modem: CableModem,
        tftp_servers: tuple[Inet, Inet] = PnmConfigManager.get_tftp_servers(),
        tftp_path: str = PnmConfigManager.get_tftp_path(),
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        super().__init__(
            DocsPnmCmCtlTest.SPECTRUM_ANALYZER,
            cable_modem,
            tftp_servers,
            tftp_path,
            cable_modem.getWriteCommunity(),
        )


class UsOfdmaChannelSpectrumAnalyzer:
    """Upstream OFDMA Channel Spectrum Analyzer Orchestrator"""

    def __init__(
        self,
        cable_modem: CableModem,
        tftp_servers: tuple[Inet, Inet] = PnmConfigManager.get_tftp_servers(),
        number_of_averages: int = 2,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cm = cable_modem
        self._number_of_averages = number_of_averages
        self._tftp_servers = tftp_servers

    async def start(self) -> list[tuple[ChannelId, MessageResponse]]:
        """Run Upstream Spectrum Captures Across All OFDMA Channels"""
        self.logger.info(f"Starting OFDMA US spectrum analysis for {self._cm.get_mac_address}")
        results = []
        return results


class UsAtdmaChannelSpectrumAnalyzer:
    """Upstream ATDMA Channel Spectrum Analyzer Orchestrator"""

    def __init__(
        self,
        cable_modem: CableModem,
        tftp_servers: tuple[Inet, Inet] = PnmConfigManager.get_tftp_servers(),
        number_of_averages: int = 2,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cm = cable_modem
        self._number_of_averages = number_of_averages
        self._tftp_servers = tftp_servers

    async def start(self) -> list[tuple[ChannelId, MessageResponse]]:
        """Run Upstream Spectrum Captures Across All ATDMA Channels"""
        self.logger.info(f"Starting ATDMA US spectrum analysis for {self._cm.get_mac_address}")
        results = []
        return results
