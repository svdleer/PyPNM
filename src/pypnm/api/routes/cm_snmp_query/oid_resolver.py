# SPDX-License-Identifier: Apache-2.0
"""Resolve MIB object names to numeric OIDs using pysnmp's local MIB collection."""

from __future__ import annotations

from functools import lru_cache
import logging
import re

logger = logging.getLogger(__name__)

# Common DOCSIS/SNMP MIB modules to search (ordered by likelihood)
_MIB_MODULES = [
    "SNMPv2-MIB",
    "IF-MIB",
    "RFC1213-MIB",
    "IP-MIB",
    "DOCS-IF-MIB",
    "DOCS-IF3-MIB",
    "DOCS-IF31-MIB",
    "DOCS-PNM-MIB",
    "DOCS-CABLE-DEVICE-MIB",
    "ENTITY-MIB",
    "HOST-RESOURCES-MIB",
    "BRIDGE-MIB",
    "DISMAN-EVENT-MIB",
]

_NUMERIC_OID_RE = re.compile(r"^[\d.]+$")


def resolve_oid(oid_input: str) -> str:
    """Resolve an OID string to its numeric form.

    Accepts:
      - Numeric: "1.3.6.1.2.1.1.3.0" → returned as-is
      - MIB name with instance: "sysUpTime.0" → resolved to "1.3.6.1.2.1.1.3.0"
      - MIB name without instance: "sysUpTime" → resolved to "1.3.6.1.2.1.1.3"

    Returns the numeric OID string, or the original input if resolution fails.
    """
    oid_input = str(oid_input).strip()
    if not oid_input:
        return oid_input

    # Already numeric
    if _NUMERIC_OID_RE.match(oid_input):
        return oid_input

    # Check static catalog first (fast, no pysnmp needed)
    from pypnm.api.routes.cm_snmp_query.mib_catalog import resolve_from_catalog
    catalog_result = resolve_from_catalog(oid_input)
    if catalog_result:
        logger.debug(f"Resolved OID '{oid_input}' → '{catalog_result}' (from catalog)")
        return catalog_result

    # Split name and instance index (e.g., "sysUpTime.0" → ("sysUpTime", "0"))
    parts = oid_input.split(".", 1)
    name = parts[0]
    instance = parts[1] if len(parts) > 1 else None

    # Try to parse instance as integer(s)
    instance_tuple: tuple = ()
    if instance is not None:
        try:
            instance_tuple = tuple(int(x) for x in instance.split("."))
        except ValueError:
            # Instance part isn't numeric — might be part of the name
            return oid_input

    try:
        from pysnmp.smi.rfc1902 import ObjectIdentity
        from pysnmp.smi import builder, view

        mib_builder = builder.MibBuilder()
        mib_view = view.MibViewController(mib_builder)

        for module in _MIB_MODULES:
            try:
                if instance_tuple:
                    oid = ObjectIdentity(module, name, *instance_tuple)
                else:
                    oid = ObjectIdentity(module, name)
                oid.resolve_with_mib(mib_view)
                resolved = oid.get_oid().prettyPrint()
                logger.debug(f"Resolved OID '{oid_input}' → '{resolved}' (via {module})")
                return resolved
            except Exception:
                continue

        logger.warning(f"Could not resolve OID name '{oid_input}' in any known MIB module")
    except Exception as exc:
        logger.warning(f"MIB resolution unavailable: {exc}")

    return oid_input


@lru_cache(maxsize=4096)
def display_oid(oid: str) -> str:
    """Return a loaded-MIB name for a numeric OID, or the numeric OID."""
    numeric = str(oid or "").strip().lstrip(".")
    if not numeric:
        return numeric
    try:
        from pypnm.snmp.compiled_oids import COMPILED_OIDS

        candidates = [
            (str(value).lstrip("."), str(name))
            for name, value in COMPILED_OIDS.items()
            if numeric == str(value).lstrip(".")
            or numeric.startswith(str(value).lstrip(".") + ".")
        ]
        if candidates:
            base_oid, symbol = max(candidates, key=lambda item: len(item[0].split(".")))
            module = (
                "DOCS-IF31-MIB" if symbol.startswith("docsIf31")
                else "DOCS-IF3-MIB" if symbol.startswith("docsIf3")
                else "DOCS-IF-MIB" if symbol.startswith("docsIf")
                else "SNMPv2-MIB" if symbol.startswith(("sys", "snmp"))
                else None
            )
            suffix = numeric[len(base_oid):]
            prefix = f"{module}::" if module else ""
            return f"{prefix}{symbol}{suffix}"
    except Exception:
        pass

    try:
        from pysnmp.smi.rfc1902 import ObjectIdentity
        from pysnmp.smi import builder, view

        mib_view = view.MibViewController(builder.MibBuilder())
        identity = ObjectIdentity(numeric)
        identity.resolve_with_mib(mib_view)
        module, symbol, indices = identity.get_mib_symbol()
        suffix = ".".join(str(index) for index in (indices or ()))
        return f"{module}::{symbol}{'.' + suffix if suffix else ''}"
    except Exception:
        return numeric
