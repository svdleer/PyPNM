# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
CMTS Vendor Detection and Vendor-Specific Logic.

Provides utilities to detect CMTS vendor and apply vendor-specific logic
for OFDMA detection, filename patterns, and other vendor-specific quirks.
"""

from enum import Enum
from typing import Optional


class CMTSVendor(Enum):
    """Supported CMTS vendors."""
    CISCO = "cisco"
    COMMSCOPE = "commscope"
    CASA = "casa"
    ARRIS = "arris"
    UNKNOWN = "unknown"


def detect_vendor(vendor_string: Optional[str] = None, model: Optional[str] = None) -> CMTSVendor:
    """
    Detect CMTS vendor from vendor string or model.
    
    Args:
        vendor_string: Vendor name from CMTS database or SNMP sysDescr
        model: Model name (e.g., "cBR-8", "E6000")
        
    Returns:
        CMTSVendor enum value
    """
    if not vendor_string and not model:
        return CMTSVendor.UNKNOWN
    
    # Normalize to lowercase for comparison
    vendor_lower = (vendor_string or "").lower()
    model_lower = (model or "").lower()
    
    # Check vendor string
    if "cisco" in vendor_lower or "cbr" in model_lower:
        return CMTSVendor.CISCO
    elif "commscope" in vendor_lower or "casa" in vendor_lower or "e6000" in model_lower or "c100g" in model_lower:
        return CMTSVendor.COMMSCOPE
    elif "casa" in vendor_lower:
        return CMTSVendor.CASA
    elif "arris" in vendor_lower:
        return CMTSVendor.ARRIS
    
    return CMTSVendor.UNKNOWN


def is_valid_ofdma_ifindex(ifindex: int, vendor: CMTSVendor, timing_offset: int = None) -> bool:
    """
    Validate OFDMA ifIndex based on vendor-specific ranges.
    
    Args:
        ifindex: Interface index to validate
        vendor: CMTS vendor
        timing_offset: Optional timing offset value (0 means no OFDMA)
        
    Returns:
        True if valid OFDMA ifIndex for this vendor
    """
    # If timing offset is provided and is 0, not an active OFDMA channel
    if timing_offset is not None and timing_offset == 0:
        return False
    
    # Vendor-specific ifIndex ranges
    if vendor == CMTSVendor.CISCO:
        # Cisco cBR-8 uses lower ifIndexes: 488334, 488335, etc.
        # Typically in the 400000-600000 range
        return 400000 <= ifindex <= 900000
    elif vendor == CMTSVendor.COMMSCOPE:
        # CommScope E6000 uses ifIndexes >= 843087000
        return ifindex >= 843087000
    elif vendor == CMTSVendor.CASA:
        # Casa CMTS uses similar range to CommScope
        return ifindex >= 843087000
    else:
        # Unknown vendor: accept if timing offset > 0 OR ifindex looks reasonable
        if timing_offset is not None:
            return timing_offset > 0
        # Accept both ranges for unknown vendors
        return (400000 <= ifindex <= 900000) or (ifindex >= 843087000)


def get_utsc_filename_pattern(vendor: CMTSVendor, mac_address: str = None, rf_port_ifindex: int = None) -> str:
    """
    Get UTSC filename glob pattern based on vendor.
    
    Args:
        vendor: CMTS vendor
        mac_address: Cable modem MAC address (for CommScope format)
        rf_port_ifindex: RF port ifIndex (for Cisco format)
        
    Returns:
        Glob pattern for UTSC files
    """
    if vendor == CMTSVendor.CISCO:
        # Cisco format: PNMCcapUsSpecAn_{hostname}_{timestamp}_{rfport}
        if rf_port_ifindex:
            return f"PNMCcapUsSpecAn_*_{rf_port_ifindex}"
        else:
            return "PNMCcapUsSpecAn_*"
    else:
        # CommScope/Casa/default format: utsc_{mac}_*
        if mac_address:
            mac_clean = mac_address.replace(":", "").replace("-", "").replace(".", "")
            return f"utsc_{mac_clean}_*"
        else:
            return "utsc_*"
