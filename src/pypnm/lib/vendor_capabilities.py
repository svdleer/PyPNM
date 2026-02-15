# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Vendor-specific cable modem capabilities.

This module provides OUI-based lookup for vendor-specific PNM capabilities,
particularly for spectrum analyzer parameters that vary by modem firmware.

The DOCSIS specification allows a wide range of parameter values, but not all
modems can handle the full range. This module provides safe defaults based on
empirical testing with different modem vendors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VendorCapabilities:
    """
    Vendor-specific PNM capabilities for a cable modem.
    
    Attributes:
        vendor: Vendor name (e.g., "Ubee", "Technicolor")
        min_spectrum_span_hz: Minimum spectrum analyzer segment span in Hz
        max_spectrum_segments: Maximum number of spectrum segments supported
    """
    vendor: str
    min_spectrum_span_hz: int = 1_000_000  # 1 MHz default (DOCSIS spec minimum)
    max_spectrum_segments: int = 1000      # Most modems support this


# OUI to vendor name mapping
# OUI is the first 3 bytes of MAC address (e.g., "90:32:4b" for Ubee)
_OUI_VENDOR_MAP: dict[str, str] = {
    # Ubee OUIs
    '00:14:d1': 'Ubee',
    '00:15:2c': 'Ubee',
    '28:c6:8e': 'Ubee',
    '58:6d:8f': 'Ubee',
    '5c:b0:66': 'Ubee',
    '64:0d:ce': 'Ubee',
    '68:b6:fc': 'Ubee',
    '78:96:84': 'Ubee',
    '90:32:4b': 'Ubee',  # UBC1318ZG (tested)
    
    # ARRIS OUIs
    '00:00:ca': 'ARRIS',
    '00:01:5c': 'ARRIS',
    '00:15:96': 'ARRIS',
    '00:15:a2': 'ARRIS',
    '00:15:a3': 'ARRIS',
    '00:15:a4': 'ARRIS',
    '00:15:a5': 'ARRIS',
    '00:1d:ce': 'ARRIS',
    '00:1d:cf': 'ARRIS',
    '00:1d:d0': 'ARRIS',
    '00:1d:d1': 'ARRIS',
    '00:1d:d2': 'ARRIS',
    '00:1d:d3': 'ARRIS',
    '00:1d:d4': 'ARRIS',
    '00:1d:d5': 'ARRIS',
    '00:23:74': 'ARRIS',
    '20:3d:66': 'ARRIS',
    '84:a0:6e': 'ARRIS',
    'e8:ed:05': 'ARRIS',
    'f0:af:85': 'ARRIS',
    'f8:0b:be': 'ARRIS',
    'fc:51:a4': 'ARRIS',
    
    # Technicolor OUIs
    '10:86:8c': 'Technicolor',
    '18:35:d1': 'Technicolor',
    '2c:39:96': 'Technicolor',
    '30:d3:2d': 'Technicolor',
    '58:23:8c': 'Technicolor',
    '70:b1:4e': 'Technicolor',
    '7c:03:4c': 'Technicolor',
    '88:f7:c7': 'Technicolor',
    '90:01:3b': 'Technicolor',
    'a0:ce:c8': 'Technicolor',
    'c8:d1:5e': 'Technicolor',
    'd4:35:1d': 'Technicolor',
    'e4:57:40': 'Technicolor',  # (tested - works with 1 MHz)
    'f4:ca:e5': 'Technicolor',
    
    # Sagemcom OUIs
    '08:95:2a': 'Sagemcom',
    '10:b3:6f': 'Sagemcom',
    '28:52:e8': 'Sagemcom',
    '30:7c:b2': 'Sagemcom',
    '44:e1:37': 'Sagemcom',
    '70:fc:8f': 'Sagemcom',
    '7c:8b:ca': 'Sagemcom',
    'a0:1b:29': 'Sagemcom',
    'a8:4e:3f': 'Sagemcom',
    'a8:70:5d': 'Sagemcom',
    'cc:33:bb': 'Sagemcom',
    'f8:08:4f': 'Sagemcom',
    
    # CISCO OUIs
    '00:1e:5a': 'CISCO',
    '00:1e:bd': 'CISCO',
    '00:22:6b': 'CISCO',
    '00:26:0a': 'CISCO',
    '00:30:f1': 'CISCO',
    '5c:50:15': 'CISCO',
    'c0:c5:20': 'CISCO',
    
    # Motorola OUIs
    '00:11:1a': 'Motorola',
    '00:12:25': 'Motorola',
    '00:14:f8': 'Motorola',
    '00:15:9a': 'Motorola',
    '00:15:d1': 'Motorola',
    '00:17:e2': 'Motorola',
    '00:18:a4': 'Motorola',
    '00:19:47': 'Motorola',
    '00:1a:66': 'Motorola',
    '00:1a:77': 'Motorola',
    '00:1c:c1': 'Motorola',
    '00:1c:fb': 'Motorola',
    '00:1d:6b': 'Motorola',
    '00:1e:46': 'Motorola',
    '00:1e:5d': 'Motorola',
    '00:1f:6b': 'Motorola',
    '00:23:be': 'Motorola',
    '00:24:95': 'Motorola',
    '00:26:41': 'Motorola',
    '00:26:42': 'Motorola',
    
    # Hitron OUIs
    '00:04:bd': 'Hitron',
    '00:26:5b': 'Hitron',
    '00:26:d8': 'Hitron',
    '68:02:b8': 'Hitron',
    'bc:14:85': 'Hitron',
    'c4:27:95': 'Hitron',
    'cc:03:fa': 'Hitron',
    
    # Juniper OUIs
    '00:1d:b5': 'Juniper',
    '00:1f:12': 'Juniper',
    '00:21:59': 'Juniper',
    '00:23:9c': 'Juniper',
    '00:26:88': 'Juniper',
}

# Vendor-specific capabilities
# These are empirically determined values based on testing
_VENDOR_CAPABILITIES: dict[str, VendorCapabilities] = {
    # Ubee UBC1318ZG tested: fails at 1 MHz (919 segs), works at 2 MHz (460 segs)
    'Ubee': VendorCapabilities(
        vendor='Ubee',
        min_spectrum_span_hz=2_000_000,  # 2 MHz minimum
        max_spectrum_segments=500,
    ),
    
    # Technicolor/Sagemcom - tested, works with 1 MHz span (919 segments)
    'Technicolor': VendorCapabilities(
        vendor='Technicolor',
        min_spectrum_span_hz=1_000_000,  # 1 MHz (full resolution)
        max_spectrum_segments=1000,
    ),
    'Sagemcom': VendorCapabilities(
        vendor='Sagemcom',
        min_spectrum_span_hz=1_000_000,  # 1 MHz (full resolution)
        max_spectrum_segments=1000,
    ),
    
    # ARRIS - generally robust, assume 1 MHz works
    'ARRIS': VendorCapabilities(
        vendor='ARRIS',
        min_spectrum_span_hz=1_000_000,
        max_spectrum_segments=1000,
    ),
    
    # Default for unknown vendors - conservative settings
    'Unknown': VendorCapabilities(
        vendor='Unknown',
        min_spectrum_span_hz=2_000_000,  # 2 MHz - safe default
        max_spectrum_segments=500,
    ),
}


def get_oui_from_mac(mac: str) -> str:
    """
    Extract the OUI (Organizationally Unique Identifier) from a MAC address.
    
    Args:
        mac: MAC address in any common format (colons, dashes, or no separators)
        
    Returns:
        OUI in lowercase colon-separated format (e.g., "90:32:4b")
    """
    if not mac:
        return ""
    
    # Normalize: lowercase, remove common separators
    normalized = mac.lower().replace('-', ':').replace('.', ':')
    
    # Handle no-separator format (e.g., "90324bc817b3")
    if ':' not in normalized and len(normalized) >= 6:
        normalized = ':'.join(normalized[i:i+2] for i in range(0, len(normalized), 2))
    
    parts = normalized.split(':')
    if len(parts) >= 3:
        return ':'.join(parts[:3])
    
    return ""


def get_vendor_from_mac(mac: str) -> str:
    """
    Get the vendor name from a MAC address using OUI lookup.
    
    Args:
        mac: MAC address in any common format
        
    Returns:
        Vendor name (e.g., "Ubee", "Technicolor") or "Unknown"
    """
    oui = get_oui_from_mac(mac)
    return _OUI_VENDOR_MAP.get(oui, 'Unknown')


def get_vendor_from_sysdescr(sys_descr: str) -> str:
    """
    Get the vendor name from SNMP sysDescr string.
    
    This provides an alternative to OUI-based detection when the MAC
    address is not available or OUI lookup fails.
    
    Args:
        sys_descr: SNMP sysDescr.0 value from the modem
        
    Returns:
        Vendor name (e.g., "Ubee", "Technicolor") or "Unknown"
        
    Example sysDescr values:
        - "Ubee DOCSIS-3.1 EMTA <<HW_REV: 2.73.1; VENDOR: Ubee; ..."
        - "ARRIS DOCSIS 3.1 Touchstone ..."
        - "Technicolor CGA4234 ..."
    """
    if not sys_descr:
        return 'Unknown'
    
    descr_lower = sys_descr.lower()
    
    # Check for vendor keywords in sysDescr
    vendor_keywords = {
        'ubee': 'Ubee',
        'arris': 'ARRIS',
        'technicolor': 'Technicolor',
        'sagemcom': 'Sagemcom',
        'cisco': 'CISCO',
        'motorola': 'Motorola',
        'hitron': 'Hitron',
        'netgear': 'Netgear',
        'commscope': 'ARRIS',  # CommScope acquired ARRIS
    }
    
    for keyword, vendor in vendor_keywords.items():
        if keyword in descr_lower:
            return vendor
    
    return 'Unknown'


def get_vendor_capabilities(mac: str) -> VendorCapabilities:
    """
    Get vendor-specific PNM capabilities for a modem based on its MAC address.
    
    Args:
        mac: MAC address of the cable modem
        
    Returns:
        VendorCapabilities with vendor-specific settings
    """
    vendor = get_vendor_from_mac(mac)
    return _VENDOR_CAPABILITIES.get(vendor, _VENDOR_CAPABILITIES['Unknown'])


def get_recommended_spectrum_span(
    mac: str,
    first_freq_hz: int,
    last_freq_hz: int,
) -> int:
    """
    Get the recommended spectrum analyzer segment span for a modem.
    
    This calculates a span that will result in a segment count within
    the modem's capabilities.
    
    Args:
        mac: MAC address of the cable modem
        first_freq_hz: First segment center frequency in Hz
        last_freq_hz: Last segment center frequency in Hz
        
    Returns:
        Recommended segment span in Hz
    """
    caps = get_vendor_capabilities(mac)
    total_span = last_freq_hz - first_freq_hz
    
    if total_span <= 0:
        return caps.min_spectrum_span_hz
    
    # Calculate minimum span needed to stay under max segment count
    min_span_for_segments = total_span // caps.max_spectrum_segments
    if min_span_for_segments < 1_000_000:
        min_span_for_segments = 1_000_000  # Minimum 1 MHz per DOCSIS spec
    
    # Use the larger of vendor minimum or calculated minimum
    recommended = max(caps.min_spectrum_span_hz, min_span_for_segments)
    
    # Round up to nearest MHz
    recommended = ((recommended + 999_999) // 1_000_000) * 1_000_000
    
    return recommended
