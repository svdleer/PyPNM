#!/usr/bin/env python3
"""
PNM MIB Capabilities Discovery Script.

Probes a CMTS to discover which DOCS-PNM-MIB tables and columns
are supported, writable, and what values they accept.

Tested on:
  - Cisco cBR-8 (IOS-XE 17.12)
  - CommScope E6000

Results help ensure the PyPNM API uses correct OIDs and data types
per vendor.

Usage:
  python3 test_pnm_capabilities.py [cmts_ip]
"""

import subprocess
import sys
import time
import re
import json
import os
from typing import Optional, Dict, List, Any

# ============================================================
# CONFIGURATION LOADING
# ============================================================

def load_config():
    """Load configuration from lab-config.json"""
    config = {
        'cmts_ip': '172.16.6.202',
        'snmp_read': 'public',
        'snmp_write': 'private',
    }
    
    # Try to load lab-config.json
    lab_config_paths = [
        '/Users/silvester/PythonDev/Git/PyPNMGui/lab-config.json',
        '../PyPNMGui/lab-config.json',
        '../../PyPNMGui/lab-config.json',
    ]
    for path in lab_config_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    lab_cfg = json.load(f)
                    if 'lab_environment' in lab_cfg:
                        test_data = lab_cfg['lab_environment'].get('test_data', {})
                        config['cmts_ip'] = test_data.get('cmts_ip', config['cmts_ip'])
                        snmp_comm = test_data.get('snmp_communities', {})
                        config['snmp_read'] = snmp_comm.get('cmts_read', config['snmp_read'])
                        config['snmp_write'] = snmp_comm.get('cmts_write', config['snmp_write'])
                        print(f"Loaded config from: {path}\n")
                        break
            except Exception as e:
                pass
    
    return config

# Load configuration
CONFIG = load_config()

# ============================================================
# CONFIGURATION
# ============================================================

CMTS_IP = CONFIG['cmts_ip']        # Override with argv[1]
SNMP_READ = CONFIG['snmp_read']
SNMP_WRITE = CONFIG['snmp_write']

# SNMP remote execution via agent container
SNMP_PREFIX = (
    'ssh labthingy '
    '"docker exec pypnm-agent-lab {cmd}"'
)

# ============================================================
# OID Tree — DOCS-PNM-MIB (1.3.6.1.4.1.4491.2.1.27)
# ============================================================

PNM = "1.3.6.1.4.1.4491.2.1.27"

# ── System-level ──
SYS_DESCR = "1.3.6.1.2.1.1.1.0"

# ── Bulk Data Transfer ──
BDT_CFG = f"{PNM}.1.1.3.1.1"           # docsPnmBulkDataTransferCfgTable
BDT_COLS = {
    "DestHostname":      (f"{BDT_CFG}.2", "s"),
    "DestHostIpAddrType":(f"{BDT_CFG}.3", "i"),
    "DestHostIpAddress": (f"{BDT_CFG}.4", "x"),
    "DestPort":          (f"{BDT_CFG}.5", "g"),
    "DestBaseUri":       (f"{BDT_CFG}.6", "s"),
    "Protocol":          (f"{BDT_CFG}.7", "i"),
    "LocalStore":        (f"{BDT_CFG}.8", "i"),
    "RowStatus":         (f"{BDT_CFG}.9", "i"),
}

# ── UTSC (Upstream Triggered Spectrum Capture) ──
UTSC_CAPAB = f"{PNM}.1.3.10.1.1"       # docsPnmCmtsUtscCapabTable
UTSC_CFG   = f"{PNM}.1.3.10.2.1"       # docsPnmCmtsUtscCfgTable
UTSC_CTRL  = f"{PNM}.1.3.10.3.1"       # docsPnmCmtsUtscCtrlTable
UTSC_STATUS= f"{PNM}.1.3.10.4.1"       # docsPnmCmtsUtscStatusTable

UTSC_CFG_COLS = {
    "LogicalChIfIndex":  (f"{UTSC_CFG}.2",  "i"),
    "TriggerMode":       (f"{UTSC_CFG}.3",  "i"),
    "MinislotCount":     (f"{UTSC_CFG}.4",  "u"),
    "Sid":               (f"{UTSC_CFG}.5",  "u"),
    "CmMacAddr":         (f"{UTSC_CFG}.6",  "x"),
    "Timeout":           (f"{UTSC_CFG}.7",  "u"),
    "CenterFreq":        (f"{UTSC_CFG}.8",  "u"),
    "Span":              (f"{UTSC_CFG}.9",  "u"),
    "NumBins":           (f"{UTSC_CFG}.10", "u"),
    "AvgSamp":           (f"{UTSC_CFG}.11", "u"),
    "Filename":          (f"{UTSC_CFG}.12", "s"),
    "EquivNoiseBw":      (f"{UTSC_CFG}.13", "u"),
    "Rbw":               (f"{UTSC_CFG}.14", "u"),
    "WindowRej":         (f"{UTSC_CFG}.15", "u"),
    "Window":            (f"{UTSC_CFG}.16", "i"),
    "OutputFormat":      (f"{UTSC_CFG}.17", "i"),
    "RepeatPeriod":      (f"{UTSC_CFG}.18", "u"),
    "FreeRunDuration":   (f"{UTSC_CFG}.19", "u"),
    "TriggerCount":      (f"{UTSC_CFG}.20", "u"),
    "RowStatus":         (f"{UTSC_CFG}.21", "i"),
    "Iuc":               (f"{UTSC_CFG}.22", "i"),
    "DestinationIndex":  (f"{UTSC_CFG}.24", "u"),
    "NumAvgs":           (f"{UTSC_CFG}.25", "u"),
}

UTSC_CAPAB_COLS = {
    "TriggerMode":   (f"{UTSC_CAPAB}.1", "BITS"),
    "OutputFormat":  (f"{UTSC_CAPAB}.2", "BITS"),
    "Window":        (f"{UTSC_CAPAB}.3", "BITS"),
    "Description":   (f"{UTSC_CAPAB}.4", "s"),
}

UTSC_CTRL_COLS = {
    "InitiateTest":  (f"{UTSC_CTRL}.1.1", "i"),
}

UTSC_STATUS_COLS = {
    "MeasStatus":    (f"{UTSC_STATUS}.1.1", "i"),
    "AvgPwr":        (f"{UTSC_STATUS}.1.2", "i"),
}

# ── US OFDMA RxMER ──
US_RXMER = f"{PNM}.1.3.7.1"            # docsPnmCmtsUsOfdmaRxMerTable
US_RXMER_COLS = {
    "Enable":         (f"{US_RXMER}.1", "i"),
    "CmMac":          (f"{US_RXMER}.2", "x"),
    "PreEq":          (f"{US_RXMER}.3", "i"),
    "NumAvgs":        (f"{US_RXMER}.4", "g"),
    "MeasStatus":     (f"{US_RXMER}.5", "i"),
    "FileName":       (f"{US_RXMER}.6", "s"),
    "DestinationIdx": (f"{US_RXMER}.7", "g"),
}

# ── DS OFDM RxMER ──
DS_RXMER = f"{PNM}.1.2.7.1"            # docsPnmCmtsDsOfdmRxMerTable
DS_RXMER_COLS = {
    "Enable":         (f"{DS_RXMER}.1", "i"),
    "CmMac":          (f"{DS_RXMER}.2", "x"),
    "NumAvgs":        (f"{DS_RXMER}.3", "g"),
    "MeasStatus":     (f"{DS_RXMER}.4", "i"),
    "FileName":       (f"{DS_RXMER}.5", "s"),
    "DestinationIdx": (f"{DS_RXMER}.6", "g"),
}

# ── DS Spectrum Analysis ──
DS_SA = f"{PNM}.1.2.1"                 # docsPnmCmtsDsSaTable (not in all vendors)

# ── DS OFDM Channel Estimate ──
DS_CHAN_EST = f"{PNM}.1.2.8.1"          # docsPnmCmtsDsOfdmChanEstCoefTable
DS_CHAN_EST_COLS = {
    "Enable":         (f"{DS_CHAN_EST}.1", "i"),
    "CmMac":          (f"{DS_CHAN_EST}.2", "x"),
    "MeasStatus":     (f"{DS_CHAN_EST}.3", "i"),
    "FileName":       (f"{DS_CHAN_EST}.4", "s"),
    "DestinationIdx": (f"{DS_CHAN_EST}.5", "g"),
}

# ── DS OFDM Symbol Capture ──
DS_SYMCAP = f"{PNM}.1.2.9"             # docsPnmCmtsDsOfdmSymbolCaptureTable

# ── DS Histogram ──
DS_HIST = f"{PNM}.1.2.6.1"             # docsPnmCmtsDsHistTable

# ── US Pre-Eq ──
US_PREEQ = f"{PNM}.1.3.2.1"            # docsPnmCmtsUsPreEqTable

# ── US Spectrum Analysis ──
US_SA = f"{PNM}.1.3.1"                 # docsPnmCmtsUsSaTable

# ── OFDMA RxMER per subcarrier (data) ──
US_RXMER_DATA = f"{PNM}.1.3.8.1"       # docsPnmCmtsUsOfdmaRxMerDataTable


# ============================================================
# SNMP Helpers
# ============================================================

def _run(cmd: str, timeout: int = 15) -> str:
    """Run command via SSH->docker, return stdout."""
    full = SNMP_PREFIX.format(cmd=cmd)
    try:
        r = subprocess.run(
            full, shell=True, capture_output=True, text=True, timeout=timeout
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        # stdout is authoritative — only fall back to stderr if stdout is empty
        # Filter MIB loading warnings from stderr
        if out:
            return out
        if err:
            # Filter out common MIB loading noise
            err_lines = [l for l in err.split('\n')
                        if not l.startswith('MIB search path:')
                        and not l.startswith('Cannot find module')
                        and l.strip()]
            if err_lines:
                return f"STDERR: {' '.join(err_lines)}"
        return "(empty)"
    except subprocess.TimeoutExpired:
        return "(timeout)"


def snmpget(oid: str) -> str:
    return _run(f"snmpget -v2c -c {SNMP_READ} -Ov {CMTS_IP} {oid}")


def snmpwalk(oid: str, max_lines: int = 50) -> List[str]:
    raw = _run(f"snmpwalk -v2c -c {SNMP_READ} -Ov {CMTS_IP} {oid}", timeout=30)
    if not raw or raw.startswith("STDERR") or raw.startswith("("):
        return []
    lines = raw.strip().split('\n')
    return lines[:max_lines]


def snmpwalk_full(oid: str, max_lines: int = 50) -> List[str]:
    """Walk with OID in output (not -Ov)."""
    raw = _run(f"snmpwalk -v2c -c {SNMP_READ} {CMTS_IP} {oid}", timeout=30)
    if not raw or raw.startswith("STDERR") or raw.startswith("("):
        return []
    lines = raw.strip().split('\n')
    return lines[:max_lines]


def snmpset(oid: str, typ: str, val) -> str:
    return _run(f"snmpset -v2c -c {SNMP_WRITE} {CMTS_IP} {oid} {typ} {val}")


# ============================================================
# Probe Functions
# ============================================================

def step(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def probe_sysdescr() -> Dict[str, str]:
    """Get sysDescr and detect vendor."""
    step("1. System Description (sysDescr)")
    raw = snmpget(SYS_DESCR)
    print(f"  {raw}")
    descr = raw.lower() if raw else ""
    vendor = "unknown"
    if 'cisco' in descr or 'cbr' in descr:
        vendor = "cisco_cbr8"
    elif 'commscope' in descr or 'arris' in descr or 'e6000' in descr:
        vendor = "commscope_e6000"
    elif 'casa' in descr:
        vendor = "casa"
    elif 'harmonic' in descr:
        vendor = "harmonic"
    print(f"  -> Vendor: {vendor}")
    return {"sysDescr": raw, "vendor": vendor}


def probe_table_exists(name: str, oid: str) -> bool:
    """Check if an SNMP table has any entries."""
    lines = snmpwalk(oid, max_lines=5)
    exists = len(lines) > 0 and not any(
        x.startswith("STDERR") or x.startswith("(") or 'No Such' in x or 'End of MIB' in x
        for x in lines
    )
    status = "SUPPORTED" if exists else "NOT FOUND"
    print(f"  {name:40s} {status}")
    if exists and lines:
        for line in lines[:3]:
            print(f"    {line[:100]}")
    return exists


def probe_columns(table_name: str, cols: Dict[str, tuple], suffix: str = "") -> Dict[str, Any]:
    """Probe each column in a table to check readability."""
    results = {}
    for col_name, (oid, typ) in cols.items():
        full_oid = f"{oid}{suffix}" if suffix else oid
        val = snmpget(full_oid) if suffix else None
        
        # If no suffix, try a walk to find any instance
        if not suffix:
            lines = snmpwalk(oid, max_lines=3)
            if lines and not any('No Such' in l or 'End of MIB' in l for l in lines):
                val = lines[0]
            else:
                val = "(not found)"
        
        supported = val and val != "(not found)" and 'No Such' not in str(val) and 'STDERR' not in str(val)
        results[col_name] = {
            "oid": oid,
            "type": typ,
            "supported": supported,
            "sample": val[:80] if val else None
        }
        marker = "OK" if supported else "--"
        print(f"    [{marker}] {col_name:25s} .{oid.split('.')[-1]:3s} ({typ})  {(val or '(none)')[:60]}")
    
    return results


def probe_utsc_capabilities(suffix: str = "") -> Dict[str, Any]:
    """Query UTSC capabilities table."""
    step("3. UTSC Capabilities (docsPnmCmtsUtscCapabTable)")
    
    # Walk the capabilities table to find any rows
    lines = snmpwalk_full(UTSC_CAPAB, max_lines=20)
    if not lines or any('No Such' in l or 'End of MIB' in l for l in lines):
        print("  (no capabilities table — vendor may not implement it)")
        return {}
    
    results = {}
    for line in lines:
        print(f"  {line[:120]}")
        # Parse trigger modes, output formats, windows from BITS
        if '.1.' in line and '=' in line:
            results["trigger_modes"] = line.split('=', 1)[-1].strip()
        elif '.2.' in line and '=' in line:
            results["output_formats"] = line.split('=', 1)[-1].strip()
        elif '.3.' in line and '=' in line:
            results["windows"] = line.split('=', 1)[-1].strip()
        elif '.4.' in line and '=' in line:
            results["description"] = line.split('=', 1)[-1].strip()
    
    return results


def probe_bdt_rows() -> Dict[str, Any]:
    """Check existing BDT rows."""
    step("4. Bulk Data Transfer (docsPnmBulkDataTransferCfgTable)")
    
    results = {}
    for idx in range(1, 6):
        rs = snmpget(f"{BDT_CFG}.9.{idx}")  # RowStatus
        if rs and 'No Such' not in rs and 'STDERR' not in rs:
            try:
                status = int(rs.split()[-1]) if rs.split() else -1
            except ValueError:
                status = -1
            status_name = {1: "active", 2: "notInService", 3: "notReady",
                          4: "createAndGo", 5: "createAndWait", 6: "destroy"}.get(status, f"unknown({status})")
            print(f"  BDT row {idx}: RowStatus={status} ({status_name})")
            
            if status == 1:
                # Read columns for active row
                for col_name in ["DestHostIpAddrType", "DestHostIpAddress", "DestPort",
                                 "DestBaseUri", "Protocol", "LocalStore"]:
                    oid, _ = BDT_COLS[col_name]
                    val = snmpget(f"{oid}.{idx}")
                    print(f"    {col_name}: {val}")
            
            results[str(idx)] = {"row_status": status, "status_name": status_name}
        else:
            break  # Stop probing after first missing row
    
    if not results:
        print("  (no BDT rows found)")
    
    return results


def probe_writable(table_name: str, cols: Dict[str, tuple], suffix: str,
                   test_values: Dict[str, Any] = None) -> Dict[str, bool]:
    """Test which columns are writable by attempting SET operations.
    
    Only runs if test_values are provided — avoids destroying config.
    """
    if not test_values:
        return {}
    
    writable = {}
    for col_name, test_val in test_values.items():
        if col_name not in cols:
            continue
        oid, typ = cols[col_name]
        result = snmpset(f"{oid}{suffix}", typ, test_val)
        ok = 'Error' not in result and 'STDERR' not in result
        writable[col_name] = ok
        marker = "RW" if ok else "RO"
        print(f"    [{marker}] {col_name:25s} SET({test_val}) -> {'OK' if ok else result[:50]}")
    
    return writable


# ============================================================
# Main
# ============================================================

def main():
    global CMTS_IP
    if len(sys.argv) > 1:
        CMTS_IP = sys.argv[1]
    
    print("=" * 70)
    print("  PNM MIB Capabilities Discovery")
    print(f"  CMTS: {CMTS_IP}")
    print("=" * 70)
    
    report: Dict[str, Any] = {"cmts_ip": CMTS_IP}
    
    # ── 1. sysDescr ──
    sys_info = probe_sysdescr()
    report["vendor"] = sys_info
    
    # ── 2. PNM Table existence ──
    step("2. PNM Table Existence Check")
    tables = {
        "BulkDataTransferCfg":       BDT_CFG,
        "UTSC Capabilities":         UTSC_CAPAB,
        "UTSC Config":               UTSC_CFG,
        "UTSC Control":              f"{UTSC_CTRL}.1",
        "UTSC Status":               f"{UTSC_STATUS}.1",
        "US OFDMA RxMER":            US_RXMER,
        "US OFDMA RxMER Data":       US_RXMER_DATA,
        "DS OFDM RxMER":             DS_RXMER,
        "DS OFDM ChanEstCoef":       DS_CHAN_EST,
        "DS Spectrum Analysis":      DS_SA,
        "DS Symbol Capture":         DS_SYMCAP,
        "DS Histogram":              DS_HIST,
        "US Pre-Eq":                 US_PREEQ,
        "US Spectrum Analysis":      US_SA,
    }
    
    table_support = {}
    for name, oid in tables.items():
        table_support[name] = probe_table_exists(name, oid)
    report["tables"] = table_support
    
    # ── 3. UTSC Capabilities ──
    capab = probe_utsc_capabilities()
    report["utsc_capabilities"] = capab
    
    # ── 4. BDT rows ──
    bdt = probe_bdt_rows()
    report["bdt_rows"] = bdt
    
    # ── 5. UTSC Config columns ──
    step("5. UTSC Config Columns (docsPnmCmtsUtscCfgTable)")
    if table_support.get("UTSC Config"):
        utsc_cols = probe_columns("UTSC Config", UTSC_CFG_COLS)
        report["utsc_config_columns"] = utsc_cols
    else:
        print("  (skipped — table not supported)")
    
    # ── 6. US OFDMA RxMER columns ──
    step("6. US OFDMA RxMER Columns (docsPnmCmtsUsOfdmaRxMerTable)")
    if table_support.get("US OFDMA RxMER"):
        rxmer_cols = probe_columns("US OFDMA RxMER", US_RXMER_COLS)
        report["us_rxmer_columns"] = rxmer_cols
    else:
        print("  (skipped — table not supported)")
    
    # ── 7. DS OFDM RxMER columns ──
    step("7. DS OFDM RxMER Columns (docsPnmCmtsDsOfdmRxMerTable)")
    if table_support.get("DS OFDM RxMER"):
        ds_rxmer_cols = probe_columns("DS OFDM RxMER", DS_RXMER_COLS)
        report["ds_rxmer_columns"] = ds_rxmer_cols
    else:
        print("  (skipped — table not supported)")
    
    # ── 8. DS Channel Estimate columns ──
    step("8. DS OFDM Channel Estimate Columns")
    if table_support.get("DS OFDM ChanEstCoef"):
        chanest_cols = probe_columns("DS OFDM ChanEstCoef", DS_CHAN_EST_COLS)
        report["ds_chanest_columns"] = chanest_cols
    else:
        print("  (skipped — table not supported)")
    
    # ── Summary ──
    step("SUMMARY")
    vendor = report["vendor"]["vendor"]
    print(f"  Vendor:    {vendor}")
    print(f"  CMTS IP:   {CMTS_IP}")
    print()
    
    supported = [name for name, ok in table_support.items() if ok]
    unsupported = [name for name, ok in table_support.items() if not ok]
    
    print(f"  Supported tables ({len(supported)}):")
    for name in supported:
        print(f"    + {name}")
    print()
    
    if unsupported:
        print(f"  Not found ({len(unsupported)}):")
        for name in unsupported:
            print(f"    - {name}")
    
    # Save report
    report_file = f"/tmp/pnm_capabilities_{CMTS_IP.replace('.', '_')}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved: {report_file}")


if __name__ == "__main__":
    main()
