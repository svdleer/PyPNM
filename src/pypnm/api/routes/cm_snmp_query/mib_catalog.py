# SPDX-License-Identifier: Apache-2.0
"""Static catalog of common DOCSIS/SNMP MIB objects for autocomplete and resolution."""

from __future__ import annotations

# Format: "objectName.instance" -> "numeric OID"
# Common CM-queryable objects (leaf nodes with typical instance suffix)
MIB_CATALOG: dict[str, str] = {
    # SNMPv2-MIB
    "sysDescr.0": "1.3.6.1.2.1.1.1.0",
    "sysObjectID.0": "1.3.6.1.2.1.1.2.0",
    "sysUpTime.0": "1.3.6.1.2.1.1.3.0",
    "sysContact.0": "1.3.6.1.2.1.1.4.0",
    "sysName.0": "1.3.6.1.2.1.1.5.0",
    "sysLocation.0": "1.3.6.1.2.1.1.6.0",
    "sysServices.0": "1.3.6.1.2.1.1.7.0",
    # IF-MIB
    "ifNumber.0": "1.3.6.1.2.1.2.1.0",
    "ifDescr": "1.3.6.1.2.1.2.2.1.2",
    "ifType": "1.3.6.1.2.1.2.2.1.3",
    "ifMtu": "1.3.6.1.2.1.2.2.1.4",
    "ifSpeed": "1.3.6.1.2.1.2.2.1.5",
    "ifPhysAddress": "1.3.6.1.2.1.2.2.1.6",
    "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
    "ifInOctets": "1.3.6.1.2.1.2.2.1.10",
    "ifOutOctets": "1.3.6.1.2.1.2.2.1.16",
    "ifInErrors": "1.3.6.1.2.1.2.2.1.14",
    "ifOutErrors": "1.3.6.1.2.1.2.2.1.20",
    # DOCS-CABLE-DEVICE-MIB
    "docsDevResetNow.0": "1.3.6.1.2.1.69.1.1.3.0",
    "docsDevSwCurrentVers.0": "1.3.6.1.2.1.69.1.3.2.0",
    "docsDevSwFilename.0": "1.3.6.1.2.1.69.1.3.3.0",
    "docsDevSwServer.0": "1.3.6.1.2.1.69.1.3.1.0",
    "docsDevServerBootState.0": "1.3.6.1.2.1.69.1.1.1.0",
    "docsDevEvFirstTime": "1.3.6.1.2.1.69.1.5.8.1.2",
    "docsDevEvText": "1.3.6.1.2.1.69.1.5.8.1.7",
    # DOCS-IF-MIB (CM downstream/upstream)
    "docsIfDownChannelId": "1.3.6.1.2.1.10.127.1.1.1.1.1",
    "docsIfDownChannelFrequency": "1.3.6.1.2.1.10.127.1.1.1.1.2",
    "docsIfDownChannelWidth": "1.3.6.1.2.1.10.127.1.1.1.1.3",
    "docsIfDownChannelModulation": "1.3.6.1.2.1.10.127.1.1.1.1.4",
    "docsIfDownChannelPower": "1.3.6.1.2.1.10.127.1.1.1.1.6",
    "docsIfSigQSignalNoise": "1.3.6.1.2.1.10.127.1.1.4.1.5",
    "docsIfSigQUnerroreds": "1.3.6.1.2.1.10.127.1.1.4.1.2",
    "docsIfSigQCorrecteds": "1.3.6.1.2.1.10.127.1.1.4.1.3",
    "docsIfSigQUncorrectables": "1.3.6.1.2.1.10.127.1.1.4.1.4",
    "docsIfUpChannelId": "1.3.6.1.2.1.10.127.1.1.2.1.1",
    "docsIfUpChannelFrequency": "1.3.6.1.2.1.10.127.1.1.2.1.2",
    "docsIfUpChannelWidth": "1.3.6.1.2.1.10.127.1.1.2.1.3",
    "docsIfCmStatusTxPower": "1.3.6.1.2.1.10.127.1.2.2.1.3",
    # DOCS-IF3-MIB
    "docsIf3CmStatusUsTxPower": "1.3.6.1.4.1.4491.2.1.20.1.2.1.1",
    "docsIf3CmStatusUsT3Timeouts": "1.3.6.1.4.1.4491.2.1.20.1.2.1.2",
    "docsIf3CmStatusUsT4Timeouts": "1.3.6.1.4.1.4491.2.1.20.1.2.1.3",
    "docsIf3CmStatusUsRangingAborteds": "1.3.6.1.4.1.4491.2.1.20.1.2.1.4",
    "docsIf3CmStatusValue": "1.3.6.1.4.1.4491.2.1.20.1.1.1.2",
    # DOCS-IF31-MIB (OFDM/OFDMA)
    "docsIf31CmDsOfdmChannelPower": "1.3.6.1.4.1.4491.2.1.28.1.1.1.2",
    "docsIf31CmDsOfdmChannelMerMean": "1.3.6.1.4.1.4491.2.1.28.1.1.1.3",
    "docsIf31CmDsOfdmChannelMerStdDev": "1.3.6.1.4.1.4491.2.1.28.1.1.1.4",
    "docsIf31CmDsOfdmChanPlcFreq": "1.3.6.1.4.1.4491.2.1.28.1.3.1.2",
    "docsIf31CmUsOfdmaChanTxPower": "1.3.6.1.4.1.4491.2.1.28.1.6.1.3",
    # DOCS-PNM-MIB
    "docsPnmCmCtlTest.0": "1.3.6.1.4.1.4491.2.1.27.1.3.1.1.0",
    "docsPnmCmCtlStatus.0": "1.3.6.1.4.1.4491.2.1.27.1.3.1.2.0",
    # IP/Networking
    "ipAdEntAddr": "1.3.6.1.2.1.4.20.1.1",
    "ipAdEntNetMask": "1.3.6.1.2.1.4.20.1.3",
    "ipForwarding.0": "1.3.6.1.2.1.4.1.0",
}

# Build reverse lookup (numeric → name) for display
_NUMERIC_TO_NAME: dict[str, str] = {v: k for k, v in MIB_CATALOG.items()}


def search_catalog(query: str, limit: int = 20) -> list[dict[str, str]]:
    """Search the MIB catalog by name prefix (case-insensitive)."""
    query_lower = query.lower().strip()
    if not query_lower:
        return []
    results = []
    for name, oid in MIB_CATALOG.items():
        if query_lower in name.lower():
            results.append({"name": name, "oid": oid})
            if len(results) >= limit:
                break
    return results


def resolve_from_catalog(name: str) -> str | None:
    """Try to resolve a MIB name from the static catalog. Returns numeric OID or None."""
    # Exact match
    if name in MIB_CATALOG:
        return MIB_CATALOG[name]
    # Case-insensitive
    name_lower = name.lower()
    for key, value in MIB_CATALOG.items():
        if key.lower() == name_lower:
            return value
    return None
