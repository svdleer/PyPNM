# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream PNM Integration

"""Upstream PNM API Module"""

from pypnm.api.routes.docs.pnm.us.ofdma import router as ofdma_router
from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer import router as spectrum_router
from pypnm.api.routes.docs.pnm.us.utsc import router as utsc_router

__all__ = ["ofdma_router", "spectrum_router", "utsc_router"]
