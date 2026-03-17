# SPDX-License-Identifier: Apache-2.0
# Fiber Node SNMP utilities — shared OID parsing for DOCS-IF3-MIB fiber node tables
#
# Used by:
#   - channel_stats/router.py: per-modem FN lookup (MAC → SG ID → FN)
#   - rxmer/router.py: CMTS-wide channel → fiber node mapping

from __future__ import annotations

from typing import Optional

# DOCS-IF3-MIB OID base
DOCS_IF3_MIB_BASE = "1.3.6.1.4.1.4491.2.1.20"

# Fiber node status table OIDs
OID_MD_NODE_STATUS_MD_DS_SG_ID = f"{DOCS_IF3_MIB_BASE}.1.12.1.3"  # dsSgId (index: mdIfIndex, strLen, fnName..., mCmSgId)
OID_MD_NODE_STATUS_MD_US_SG_ID = f"{DOCS_IF3_MIB_BASE}.1.12.1.4"  # usSgId (index: mdIfIndex, strLen, fnName..., mCmSgId)
OID_MD_CH_CFG_CH_ID = f"{DOCS_IF3_MIB_BASE}.1.5.1.3"             # chId (index: mdIfIndex, chIfIndex)
OID_MD_US_SG_STATUS_CH_SET_ID = f"{DOCS_IF3_MIB_BASE}.1.14.1.2"  # chSetId (index: mdIfIndex, mUSsgId)
OID_US_CH_SET_CH_LIST = f"{DOCS_IF3_MIB_BASE}.1.22.1.2"          # channel list (index: mdIfIndex, chSetId)


def parse_fn_name_from_oid(oid: str, prefix: str) -> Optional[tuple[str, int, int]]:
    """
    Parse fiber node name and related IDs from a DOCS-IF3-MIB OID.
    
    The docsIf3MdNodeStatus table uses a string-indexed OID format:
        {prefix}.{mdIfIndex}.{strLen}.{char0}.{char1}...{charN}.{mCmSgId}
    where strLen is the length of the FN name and char0..charN are ASCII bytes.
    
    Args:
        oid: Full OID string (e.g. "1.3.6.1.4.1.4491.2.1.20.1.12.1.3.536871013.3.70.78.49.1")
        prefix: OID prefix to strip (e.g. "1.3.6.1.4.1.4491.2.1.20.1.12.1.3")
    
    Returns:
        Tuple of (fn_name, md_if_index, m_cm_sg_id) or None if parsing fails
    """
    if not oid.startswith(prefix + "."):
        return None
    
    suffix = oid[len(prefix) + 1:]
    parts = suffix.split('.')
    
    # Minimum: mdIfIndex, strLen, at least 1 char, mCmSgId = 4 parts
    if len(parts) < 4:
        return None
    
    try:
        md_if_index = int(parts[0])
        str_len = int(parts[1])
        
        # Validate we have enough parts for the name + mCmSgId
        if len(parts) < 2 + str_len + 1:
            return None
        
        # Extract ASCII characters
        char_parts = parts[2:2 + str_len]
        ascii_values = [int(p) for p in char_parts]
        
        # Validate printable ASCII range
        if not all(32 <= v <= 126 for v in ascii_values):
            return None
        
        fn_name = ''.join(chr(v) for v in ascii_values)
        m_cm_sg_id = int(parts[2 + str_len])
        
        return (fn_name, md_if_index, m_cm_sg_id)
    except (ValueError, IndexError):
        return None


def parse_fn_name_from_oid_by_sg_id(oid: str, prefix: str, target_sg_id: int) -> Optional[str]:
    """
    Parse fiber node name from OID if it matches the target service group ID.
    
    This is a convenience wrapper for per-modem lookups where we already know
    the CM's service group ID and just need to find the matching FN name.
    
    Args:
        oid: Full OID string
        prefix: OID prefix to strip
        target_sg_id: Service group ID to match (from OID suffix)
    
    Returns:
        Fiber node name if OID ends with target_sg_id, None otherwise
    """
    if not oid.endswith(f".{target_sg_id}"):
        return None
    
    result = parse_fn_name_from_oid(oid, prefix)
    if result and result[2] == target_sg_id:
        return result[0]
    return None


def parse_channel_id_list(val) -> frozenset:
    """
    Parse DOCS-IF3-MIB ChannelList (OCTET STRING) into a frozenset of integer channel IDs.
    
    The agent may return various formats:
      - bytes b'\\x01\\x02\\x03\\x04\\x19\\x1a'  ← raw octet string (most common)
      - str   '1,2,3,4,25,26'                    ← comma-separated (some agents)
      - str   '01 02 03 04 19 1a'                ← hex-spaced
      - str   '0x0102...'                        ← 0x-prefixed hex
    
    Returns:
        frozenset of integer channel IDs
    """
    if isinstance(val, (bytes, bytearray)):
        return frozenset(val)
    
    s = str(val).strip().strip('"')
    
    # Raw Python repr of bytes: starts with b' or b"
    if s.startswith("b'") or s.startswith('b"'):
        try:
            return frozenset(c for c in eval(s))  # safe: only byte literals
        except Exception:
            pass
    
    # Escape sequences like \x01\x02 in a plain string
    if '\\x' in s:
        try:
            return frozenset(c for c in bytes.fromhex(s.replace('\\x', '')))
        except Exception:
            pass
    
    # Comma-separated integers: "1,2,3,4,25,26"
    if ',' in s:
        return frozenset(int(x.strip()) for x in s.split(',') if x.strip().isdigit())
    
    # Space-separated hex bytes: "01 02 03 04 19 1a"
    if ' ' in s or s.startswith('0x'):
        try:
            return frozenset(int(b, 16) for b in s.replace('0x', '').split())
        except ValueError:
            pass
    
    # Single printable chars that are control chars (raw octet string as str)
    if s and all(ord(c) < 256 for c in s):
        ids = frozenset(ord(c) for c in s)
        if ids:
            return ids
    
    return frozenset()
