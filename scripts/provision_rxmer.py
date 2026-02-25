#!/usr/bin/env python3
"""
US OFDMA RxMER provisioning script — CommScope E6000, Casa 100G, Cisco cBR-8.

docsPnmCmtsUsOfdmaRxMerTable  (1.3.6.1.4.1.4491.2.1.27.1.3.7.1)
  .1  Enable           (i: 1=true 2=false)  — also the trigger
  .2  CmMac            (x)
  .3  PreEq            (i: 1=true 2=false)
  .4  NumAvgs          (g)
  .5  MeasStatus       (read-only)
  .6  FileName         (s)
  .7  DestinationIndex (u)

Flow:
  0. sysDescr  → detect vendor
  1. BDT       → set TFTP destination (vendor-specific)
  2. RxMER     → set CmMac, FileName, PreEq, NumAvgs, DestinationIndex
  3. Enable=1  → trigger capture
  4. Poll MeasStatus until sampleReady
  5. Stop      → Enable=2

Usage:
    python3 provision_rxmer.py <cmts_ip> <ofdma_ifindex> <cm_mac>

    python3 provision_rxmer.py 172.16.6.202 488046 aa:bb:cc:dd:ee:ff   # Cisco cBR-8
    python3 provision_rxmer.py 172.16.6.201 4000048 aa:bb:cc:dd:ee:ff  # Casa 100G
    python3 provision_rxmer.py 172.16.6.200 1376387073 aa:bb:cc:dd:ee:ff  # E6000

Environment:
    SNMP_READ   — read community  (default: public)
    SNMP_WRITE  — write community (default: private)
    TFTP_IP     — TFTP server IP  (default: 172.16.6.101)
    TFTP_IP_CCAP  — CCAP (Casa/Cisco) TFTP IP (default: 172.22.147.18)
"""

import os
import subprocess
import sys
import time

# ============================================================
# Configuration
# ============================================================

if len(sys.argv) < 4:
    print(__doc__)
    sys.exit(1)

CMTS_IP   = sys.argv[1]
OFDMA_IDX = int(sys.argv[2])
CM_MAC    = sys.argv[3]          # aa:bb:cc:dd:ee:ff

SNMP_READ  = os.environ.get("SNMP_READ",  "public")
SNMP_WRITE = os.environ.get("SNMP_WRITE", "private")
TFTP_IP    = os.environ.get("TFTP_IP",    "172.16.6.101")
TFTP_IP_CCAP  = os.environ.get("TFTP_IP_CCAP",  "172.22.147.18")
TFTP_PATH  = "./"

# RxMER parameters
BDT_ROW       = 1
FILENAME      = "us_rxmer"
PRE_EQ        = 1    # 1=true (include pre-equalizer coefficients)
NUM_AVGS      = 1    # number of averages

# Polling
POLL_INTERVAL = 3    # seconds between polls
POLL_TIMEOUT  = 120  # seconds before giving up

# ============================================================
# OIDs
# ============================================================

PNM = "1.3.6.1.4.1.4491.2.1.27"

# docsPnmCmtsUsOfdmaRxMerTable
OID_RXMER         = f"{PNM}.1.3.7.1"
OID_RXMER_ENABLE  = f"{OID_RXMER}.1"
OID_RXMER_CM_MAC  = f"{OID_RXMER}.2"
OID_RXMER_PRE_EQ  = f"{OID_RXMER}.3"
OID_RXMER_AVGS    = f"{OID_RXMER}.4"
OID_RXMER_STATUS  = f"{OID_RXMER}.5"
OID_RXMER_FILE    = f"{OID_RXMER}.6"
OID_RXMER_DEST    = f"{OID_RXMER}.7"

# docsPnmBulkDataTransferCfgTable  (Cisco / E6000)
OID_BDT_E6000 = f"{PNM}.1.1.3.1.1"

# docsPnmCcapBulkDataControlTable  (Casa)
OID_BDT_CASA  = f"{PNM}.1.1.1.5.1"

# sysDescr
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_IF_DESCR  = "1.3.6.1.2.1.2.2.1.2"

# RowStatus values
RS_ACTIVE        = 1
RS_DESTROY       = 6
RS_CREATE_AND_GO = 4

MEAS_STATUS = {
    1: "other",
    2: "inactive",
    3: "busy",
    4: "sampleReady",
    5: "error",
    6: "resourceUnavailable",
    7: "sampleTruncated",
}

# Hex conversion
TFTP_HEX = "".join(f"{int(o):02X}" for o in TFTP_IP.split("."))

# ============================================================
# SNMP helpers
# ============================================================

SNMP_PREFIX = 'ssh access-engineering.nl "docker exec pypnm-agent-lab {cmd}"'


def _run(cmd: str) -> str:
    full = SNMP_PREFIX.format(cmd=cmd) if SNMP_PREFIX else cmd
    r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=30)
    out = r.stdout.strip()
    if r.returncode != 0 and r.stderr.strip():
        for line in r.stderr.strip().splitlines():
            if "Cannot find module" not in line and "MIB search" not in line:
                print(f"    stderr: {line}")
    return out


def snmpget(oid: str) -> str:
    return _run(f"snmpget -v2c -c {SNMP_READ} -Ov {CMTS_IP} {oid}")


def snmpset(oid: str, t: str, v) -> str:
    return _run(f"snmpset -v2c -c {SNMP_WRITE} {CMTS_IP} {oid} {t} {v}")


def val(raw: str) -> int:
    try:
        return int(raw.split(":")[-1].strip())
    except (ValueError, IndexError):
        return -1


def step(name: str):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


# ============================================================
# Vendor detection
# ============================================================

def detect_vendor() -> tuple[str, str]:
    """Returns (vendor, raw_sysdescr).
    vendor: 'e6000' | 'casa' | 'cisco' | 'evo' | 'unknown'
    """
    raw = snmpget(OID_SYS_DESCR)
    low = raw.lower()
    if "cisco" in low or "cbr" in low:
        return "cisco", raw
    if "casa" in low:
        return "casa", raw
    if "arris" in low or "cer_v" in low:
        return "e6000", raw
    if "evo" in low or "vcmts" in low:
        return "evo", raw
    return "unknown", raw


# ============================================================
# BDT setup (vendor-specific, same as provision_utsc.py)
# ============================================================

def configure_bdt_cisco(row: int):
    """Cisco BDT: docsPnmBulkDataTransferCfgTable."""
    tftp = TFTP_IP_CCAP
    tftp_hex = "".join(f"{int(o):02X}" for o in tftp.split("."))
    step(f"BDT row {row} — Cisco (docsPnmBulkDataTransferCfgTable) — TFTP {tftp}")
    snmpset(f"{OID_BDT_E6000}.9.{row}", "i", RS_DESTROY)
    time.sleep(2)
    print(f"  RowStatus.{row} = createAndGo(4)")
    r = snmpset(f"{OID_BDT_E6000}.9.{row}", "i", RS_CREATE_AND_GO)
    print(f"    {r}")
    time.sleep(1)
    fields = [
        (f"{OID_BDT_E6000}.3.{row}", "i", 1,        "DestHostIpAddrType = ipv4(1)"),
        (f"{OID_BDT_E6000}.4.{row}", "x", tftp_hex,  f"DestHostIpAddress  = {tftp}"),
        (f"{OID_BDT_E6000}.6.{row}", "s", f"tftp://{tftp}/", f"DestBaseUri        = tftp://{tftp}/"),
    ]
    for oid, t, v, desc in fields:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")


def configure_bdt_e6000(row: int):
    """E6000 BDT: docsPnmBulkDataTransferCfgTable."""
    step(f"BDT row {row} — E6000 (docsPnmBulkDataTransferCfgTable) — TFTP {TFTP_IP}")
    fields = [
        (f"{OID_BDT_E6000}.3.{row}", "i", 1,        "DestHostIpAddrType = ipv4(1)"),
        (f"{OID_BDT_E6000}.4.{row}", "x", TFTP_HEX,  f"DestHostIpAddress  = {TFTP_IP}"),
        (f"{OID_BDT_E6000}.7.{row}", "i", 1,        "Protocol          = tftp(1)"),
    ]
    for oid, t, v, desc in fields:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")


def configure_bdt_casa(row: int, tftp_ip: str = None):
    """Casa BDT: docsPnmCcapBulkDataControlTable."""
    if tftp_ip is None:
        tftp_ip = TFTP_IP_CCAP
    tftp_hex = "".join(f"{int(o):02X}" for o in tftp_ip.split("."))
    step(f"BDT CCAP row {row} — Casa (docsPnmCcapBulkDataControlTable) — TFTP {tftp_ip}")
    r = snmpset(f"{OID_BDT_CASA}.2.{row}", "i", 1)
    print(f"  DestIpAddrType = ipv4(1)  {r}")
    r = snmpset(f"{OID_BDT_CASA}.3.{row}", "x", tftp_hex)
    print(f"  DestIpAddr     = {tftp_ip}  {r}")
    r = snmpset(f"{OID_BDT_CASA}.4.{row}", "s", TFTP_PATH)
    print(f"  DestPath       = {TFTP_PATH}  {r}")
    r = snmpset(f"{OID_BDT_CASA}.5.{row}", "i", 3)
    print(f"  UploadControl  = autoUpload(3)  {r}")
    # PnmTestSelector: bit5 = usOfdmaRxMer
    r = snmpset(f"{OID_BDT_CASA}.6.{row}", "x", "0x0400")
    print(f"  PnmTestSelector= 0x0400 (usOfdmaRxMer)  {r}")


# ============================================================
# RxMER trigger + poll
# ============================================================

def discover_dest_index_casa(ofdma_idx: int) -> int:
    """Read docsPnmCmtsUsOfdmaRxMerDestinationIndex from Casa (read-only).
    Returns the index Casa expects, or 1 as fallback.
    """
    raw = snmpget(f"{OID_RXMER_DEST}.{ofdma_idx}")
    v = val(raw)
    if v > 0:
        print(f"  DestinationIndex (readback) = {v}")
        return v
    print(f"  DestinationIndex not set (raw={raw!r}) — defaulting to 1")
    return 1

def configure_rxmer(ofdma_idx: int, cm_mac: str, dest_index: int, vendor: str):
    """Set RxMER parameters and fire Enable=1."""
    idx = f".{ofdma_idx}"
    step(f"RxMER configure  ofdma_ifindex={ofdma_idx}  cm_mac={cm_mac}")

    # CM MAC: remove separators, set as hex
    mac_hex = cm_mac.replace(":", "").replace("-", "").upper()

    params = [
        (f"{OID_RXMER_CM_MAC}{idx}",  "x", mac_hex,     f"CmMac            = {cm_mac}"),
        (f"{OID_RXMER_FILE}{idx}",    "s", FILENAME,     f"FileName         = {FILENAME}"),
        (f"{OID_RXMER_PRE_EQ}{idx}",  "i", PRE_EQ,       f"PreEq            = {PRE_EQ} (1=with pre-eq)"),
        (f"{OID_RXMER_AVGS}{idx}",    "u", NUM_AVGS,      f"NumAvgs          = {NUM_AVGS}"),
    ]
    # Casa manages DestinationIndex internally — notWritable
    if vendor != "casa":
        params.append((f"{OID_RXMER_DEST}{idx}", "u", dest_index, f"DestinationIndex = {dest_index}"))
    for oid, t, v, desc in params:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")
        time.sleep(0.05)

    step(f"Enable=1  (trigger)  ofdma_ifindex={ofdma_idx}")
    r = snmpset(f"{OID_RXMER_ENABLE}{idx}", "i", 1)
    print(f"  {r}")


def poll(ofdma_idx: int) -> bool:
    step("Poll MeasStatus")
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > POLL_TIMEOUT:
            print(f"\n  timeout after {POLL_TIMEOUT}s")
            return False
        raw = snmpget(f"{OID_RXMER_STATUS}.{ofdma_idx}")
        s = val(raw)
        name = MEAS_STATUS.get(s, "unknown")
        print(f"  [{elapsed:5.1f}s]  MeasStatus={s} ({name})")
        if s == 4:
            print("\n  sampleReady — check TFTP server")
            return True
        if s == 7:
            print("\n  sampleTruncated")
            return True
        if s in (5, 6):
            print(f"\n  {name}")
            return False
        time.sleep(POLL_INTERVAL)


# ============================================================
# Main
# ============================================================

def main():
    step("0. Vendor detection")
    vendor, sysdescr = detect_vendor()
    print(f"  vendor   : {vendor}")
    print(f"  sysDescr : {sysdescr[:100]}")

    if vendor == "evo":
        print("\n  CommScope EVO vCCAP — coming soon.")
        sys.exit(0)
    if vendor == "unknown":
        print("\n  Unknown vendor — proceeding with E6000 defaults. Check results carefully.")

    # BDT setup
    bdt_row = BDT_ROW
    if vendor == "cisco":
        configure_bdt_cisco(bdt_row)
    elif vendor == "casa":
        # Casa manages DestinationIndex internally — read it back to know which row to provision
        step("BDT discovery — reading Casa DestinationIndex")
        bdt_row = discover_dest_index_casa(OFDMA_IDX)
        configure_bdt_casa(bdt_row)
    elif vendor in ("e6000", "unknown"):
        configure_bdt_e6000(bdt_row)

    try:
        configure_rxmer(OFDMA_IDX, CM_MAC, bdt_row, vendor)
        poll(OFDMA_IDX)
    except KeyboardInterrupt:
        print("\n\nInterrupted")
        sys.exit(1)
    finally:
        print(f"\n  Stop  Enable=2  ofdma_ifindex={OFDMA_IDX}")
        r = snmpset(f"{OID_RXMER_ENABLE}.{OFDMA_IDX}", "i", 2)
        print(f"    {r}")


if __name__ == "__main__":
    main()
