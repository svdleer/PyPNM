#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026
"""
UTSC provisioning script for CommScope EVO vCCAP (CASA DCTS VCCAP, HW=CASA-VNF).

Key differences from E6000:
    - No pre-provisioned rows — must create with createAndWait(5), set all params, then active(1)
    - createAndGo(4) returns commitFailed (mandatory objects must be set before activation)
    - Row index: physicalIfIndex  (e.g. 40001280)
    - Uses local snmpget/snmpset binaries from PATH

Interface types on EVO:
  Physical RF port:   ifIndex 40001280+   ifName "RPHY Upstream Physical Interface 1:0/0.0"
                      -> Used as UTSC cfg TABLE INDEX (row key)
  Logical OFDMA ch:   ifIndex 160001280+  ifName "RPHY OFDMA Upstream 1:0/0.0/0"
                      -> Used as LogicalChIfIndex (.2) to pin capture to one OFDMA channel
                         Set to 0 to capture any/all channels on the physical port
  Mapping (physical -> logical OFDMA):
    40001280 (1:0/0.0)  -> 160001280
    40001281 (1:0/0.1)  -> 160001282
    40001296 (1:0/1.0)  -> 160001296
    40001297 (1:0/1.1)  -> 160001298

  ifIndex ranges on EVO:
    40001280+   RPHY Upstream Physical Interface (SC-QAM + OFDMA physical)
    120001280+  SC-QAM upstream logical channels
    160001280+  RPHY OFDMA Upstream logical channels

  IMPORTANT: docsPnmCmtsUtscCapabTriggerMode = BITS: 00 00 on ALL ports.
  This means UTSC is NOT supported / not licensed on this EVO firmware (10.10.0).
  All createAndWait/createAndGo attempts will fail with commitFailed.
  This script runs the attempt anyway to document the exact failure mode.
Device: MND-GT0002-CCAPV001  172.16.6.160

Usage:
    python3 provision_utsc_evo.py [physical_ifindex [logical_ifindex]]
    python3 provision_utsc_evo.py 40001280              # any logical channel
    python3 provision_utsc_evo.py 40001280 160001280    # pin to specific OFDMA channel
"""

import subprocess
import sys
import os
import time
import shlex

# ============================================================
# CONFIGURATION  (override via environment variables)
# ============================================================

CMTS_IP    = os.environ.get("CMTS_IP",    "172.16.6.160")
SNMP_READ  = os.environ.get("SNMP_READ",  "Z1gg0@LL")
SNMP_WRITE = os.environ.get("SNMP_WRITE", "Z1gg0Sp3c1@l")
REMOTE_HOST = os.environ.get("REMOTE_HOST", "access-engineering.nl")

RF_ARG_GIVEN = len(sys.argv) > 1
RF_PORT    = int(sys.argv[1]) if len(sys.argv) > 1 else 40001280  # physical RF port
LOGICAL_CH = int(sys.argv[2]) if len(sys.argv) > 2 else 160001280  # logical OFDMA ch

# Try both common EVO index forms.
IDX_CANDIDATES = [f".{RF_PORT}", f".{RF_PORT}.1"]


# TFTP
TFTP_IP    = os.environ.get("TFTP_IP", "172.16.6.101")
TFTP_HEX   = "".join(f"{int(o):02X}" for o in TFTP_IP.split("."))  # AC100665
TFTP_URI   = f"tftp://{TFTP_IP}/"

# BDT row (destination table)
BDT_ROW    = 1
BDT_BASE   = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"

# UTSC tables
UTSC_BASE  = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
CTRL_BASE  = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1"
STAT_BASE  = "1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1"

# RowStatus values
RS_ACTIVE        = 1
RS_CREATE_WAIT   = 5   # createAndWait — set mandatory fields before active(1)
RS_DESTROY       = 6

# Capture parameters — start conservative to find EVO limits
TRIGGER_MODE     = 2        # freeRunning
CENTER_FREQ      = 16000000 # 16 MHz
SPAN             = 30000000 # 30 MHz
NUM_BINS         = 800
OUTPUT_FORMAT    = 5        # fftAmplitude (same as Casa)
WINDOW           = 2        # rectangular (safe default)
REPEAT_PERIOD    = 100000   # 100 ms (100000 µs)
FREERUN_DURATION = 120000   # 120 s (120 000 ms) — Casa/EVO minimum
TRIGGER_COUNT    = 1
FILENAME         = "utsc_evo"
SKIP_ROW_LIFECYCLE = os.environ.get("SKIP_ROW_LIFECYCLE", "1") == "1"
SKIP_UTSC_DESTROY = os.environ.get("SKIP_UTSC_DESTROY", "1") == "1"

MEAS_STATUS = {
    1: "other", 2: "inactive", 3: "triggered",
    4: "sampleReady", 5: "error", 6: "measurementBusy", 7: "sampleTruncated"
}

POLL_INTERVAL = 3
POLL_TIMEOUT  = 180

# ============================================================
# SNMP helpers — run on REMOTE_HOST via SSH (or locally if REMOTE_HOST is empty)
# ============================================================

def _run(cmd: str) -> str:
    full = cmd
    if REMOTE_HOST:
        full = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {REMOTE_HOST} {shlex.quote(cmd)}"
    r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=20)
    out = r.stdout.strip()
    if r.returncode != 0:
        for line in r.stderr.strip().splitlines():
            if "Cannot find module" not in line and "MIB search" not in line:
                print(f"    STDERR: {line}")
    return out


def snmpget(oid: str) -> str:
    return _run(f"snmpget -v2c -c {SNMP_READ} -Ov {CMTS_IP} {oid}")


def snmpset(oid: str, t: str, v) -> str:
    return _run(f"snmpset -v2c -c {SNMP_WRITE} {CMTS_IP} {oid} {t} {v}")


def snmpwalk(oid: str) -> str:
    return _run(f"snmpwalk -v2c -c {SNMP_READ} -On {CMTS_IP} {oid}")


def val(raw: str) -> int:
    try:
        return int(raw.split(":")[-1].strip())
    except (ValueError, IndexError):
        return -1


def step(name: str):
    print(f"\n{'='*60}\n  {name}\n{'='*60}")


CAPAB_OID  = "1.3.6.1.4.1.4491.2.1.27.1.3.10.1.1.2"  # docsPnmCmtsUtscCapabTriggerMode
SYS_DESCR_OID = "1.3.6.1.2.1.1.1.0"


def auto_select_vccap_rf_port():
    """If user did not pass RF index and device is vCCAP, default to 120001280."""
    global RF_PORT, IDX_CANDIDATES
    if RF_ARG_GIVEN:
        return
    raw = snmpget(SYS_DESCR_OID)
    sysdescr = raw.lower()
    if "vccap" in sysdescr or "dcts vccap" in sysdescr:
        RF_PORT = 120001280
        IDX_CANDIDATES = [f".{RF_PORT}", f".{RF_PORT}.1"]
        print(f"  Auto-detected vCCAP from sysDescr; using RF port {RF_PORT}")


def check_capability():
    """Check if UTSC is advertised as supported on RF_PORT."""
    step("0. Capability Check (docsPnmCmtsUtscCapabTriggerMode)")
    raw = snmpget(f"{CAPAB_OID}.{RF_PORT}")
    print(f"  CapabTriggerMode.{RF_PORT} = {raw}")
    cap_unsupported = (
        raw == ""
        or "No Such" in raw
        or "Hex-STRING: 00" in raw
        or "BITS: 00" in raw
        or "00 00" in raw
    )
    if cap_unsupported:
        print(f"\n  *** WARNING: TriggerMode capability = 00 00 (all zeros)")
        print(f"  *** UTSC is NOT supported on this port/firmware.")
        print(f"  *** EVO firmware 10.10.0 — feature may require upgrade or license.")
        print(f"  *** Continuing anyway to document failure mode...\n")
    else:
        print(f"  -> Capability bits set — UTSC may be supported")



# ============================================================

def provision_bdt():
    step(f"1. BDT Row {BDT_ROW} — TFTP {TFTP_IP}")

    # destroy existing row first (ignore error if it doesn't exist)
    print(f"  RowStatus.{BDT_ROW} = destroy(6)")
    snmpset(f"{BDT_BASE}.9.{BDT_ROW}", "i", RS_DESTROY)
    time.sleep(1)

    # createAndWait, then set fields, then active
    print(f"  RowStatus.{BDT_ROW} = createAndWait(5)")
    r = snmpset(f"{BDT_BASE}.9.{BDT_ROW}", "i", RS_CREATE_WAIT)
    print(f"    {r}")
    time.sleep(0.5)

    fields = [
        (f"{BDT_BASE}.3.{BDT_ROW}", "i", 1,         "DestHostIpAddrType = ipv4(1)"),
        (f"{BDT_BASE}.4.{BDT_ROW}", "x", TFTP_HEX,  f"DestHostIpAddress  = {TFTP_IP}"),
        (f"{BDT_BASE}.6.{BDT_ROW}", "s", TFTP_URI,  f"DestBaseUri        = {TFTP_URI}"),
        (f"{BDT_BASE}.7.{BDT_ROW}", "i", 1,          "Protocol           = tftp(1)"),
    ]
    for oid, t, v, desc in fields:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")

    print(f"  RowStatus.{BDT_ROW} = active(1)")
    r = snmpset(f"{BDT_BASE}.9.{BDT_ROW}", "i", RS_ACTIVE)
    print(f"    {r}")

# ============================================================
# UTSC config row
# ============================================================

def configure_utsc_for_idx(idx: str) -> bool:
    step(f"2. UTSC Row {idx}")

    if not SKIP_ROW_LIFECYCLE:
        # destroy any existing row unless explicitly skipped
        if not SKIP_UTSC_DESTROY:
            print(f"  RowStatus{idx} = destroy(6)")
            snmpset(f"{UTSC_BASE}.21{idx}", "i", RS_DESTROY)
            time.sleep(2)
        else:
            print("  Skipping UTSC RowStatus destroy (SKIP_UTSC_DESTROY=1)")

        # createAndWait — EVO rejects createAndGo(4) with commitFailed
        print(f"  RowStatus{idx} = createAndWait(5)")
        r = snmpset(f"{UTSC_BASE}.21{idx}", "i", RS_CREATE_WAIT)
        print(f"    {r}")
        time.sleep(0.5)

        # Fail fast if EVO rejects row creation for this index.
        rs_after_create = snmpget(f"{UTSC_BASE}.21{idx}")
        print(f"  RowStatus after createAndWait: {rs_after_create}")
        if "No Such" in rs_after_create or rs_after_create.strip() == "":
            print("\n  ERROR: UTSC row was not created for this index.")
            print(f"  Index attempt failed: {idx}")
            return False
    else:
        print("  Skipping RowStatus destroy/createAndWait (SKIP_ROW_LIFECYCLE=1)")

    # Set all mandatory + optional parameters while row is notReady/notInService
    params = [
        (f"{UTSC_BASE}.2{idx}",  "i", LOGICAL_CH,      f"LogicalChIfIndex   = {LOGICAL_CH} {'(any channel)' if LOGICAL_CH == 0 else '(pinned OFDMA ch)'}"),
        (f"{UTSC_BASE}.3{idx}",  "i", TRIGGER_MODE,    f"TriggerMode        = {TRIGGER_MODE} (freeRunning)"),
        (f"{UTSC_BASE}.8{idx}",  "u", CENTER_FREQ,     f"CenterFreq         = {CENTER_FREQ//1000000} MHz"),
        (f"{UTSC_BASE}.9{idx}",  "u", SPAN,            f"Span               = {SPAN//1000000} MHz"),
        (f"{UTSC_BASE}.10{idx}", "u", NUM_BINS,        f"NumBins            = {NUM_BINS}"),
        (f"{UTSC_BASE}.17{idx}", "i", OUTPUT_FORMAT,   f"OutputFormat       = {OUTPUT_FORMAT} (fftAmplitude)"),
        (f"{UTSC_BASE}.16{idx}", "i", WINDOW,          f"Window             = {WINDOW} (rectangular)"),
        (f"{UTSC_BASE}.18{idx}", "u", REPEAT_PERIOD,   f"RepeatPeriod       = {REPEAT_PERIOD} µs"),
        (f"{UTSC_BASE}.19{idx}", "u", FREERUN_DURATION,f"FreeRunDuration    = {FREERUN_DURATION} ms"),
        (f"{UTSC_BASE}.20{idx}", "u", TRIGGER_COUNT,   f"TriggerCount       = {TRIGGER_COUNT}"),
        (f"{UTSC_BASE}.12{idx}", "s", FILENAME,        f"Filename           = {FILENAME}"),
        (f"{UTSC_BASE}.24{idx}", "u", BDT_ROW,         f"DestinationIndex   = {BDT_ROW}"),
    ]
    for oid, t, v, desc in params:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")
        time.sleep(0.05)

    # Activate row
    print(f"  RowStatus{idx} = active(1)")
    r = snmpset(f"{UTSC_BASE}.21{idx}", "i", RS_ACTIVE)
    print(f"    {r}")
    time.sleep(0.5)

    # Verify row is now active
    rs = snmpget(f"{UTSC_BASE}.21{idx}")
    print(f"  RowStatus readback: {rs}")
    if "No Such" in rs or rs.strip() == "":
        print("\n  ERROR: UTSC row is still missing after activation attempt.")
        return False
    return True


def configure_utsc() -> str | None:
    errors = []
    for idx in IDX_CANDIDATES:
        ok = configure_utsc_for_idx(idx)
        if ok:
            print(f"\n  UTSC configuration succeeded with index {idx}")
            return idx
        errors.append(idx)
        print(f"\n  Index {idx} failed, continuing with next candidate...")

    print("\n  ERROR: UTSC configuration failed for all index candidates.")
    print(f"  Tried: {', '.join(errors)}")
    return None

# ============================================================
# Trigger + poll
# ============================================================

def trigger(idx: str):
    step(f"3. Trigger (InitiateTest=1) {idx}")
    r = snmpset(f"{CTRL_BASE}{idx}", "i", 1)
    print(f"  {r}")


def poll_status(idx: str):
    step(f"4. Poll MeasStatus {idx}")
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > POLL_TIMEOUT:
            print(f"\n  TIMEOUT after {POLL_TIMEOUT}s")
            return False
        raw = snmpget(f"{STAT_BASE}{idx}")
        s = val(raw)
        name = MEAS_STATUS.get(s, "unknown")
        print(f"  [{elapsed:5.1f}s] MeasStatus={s} ({name})")
        if s == 4:
            print("\n  sampleReady — check TFTP server!")
            return True
        elif s == 7:
            print("\n  sampleTruncated")
            return True
        elif s in (5, 6):
            print(f"\n  {name}!")
            return False
        time.sleep(POLL_INTERVAL)

# ============================================================
# Main
# ============================================================

def main():
    auto_select_vccap_rf_port()
    print("=" * 60)
    print("  UTSC Test — CommScope EVO vCCAP (CASA DCTS VCCAP)")
    print(f"  Device:    MND-GT0002-CCAPV001  {CMTS_IP}")
    print(f"  RF port:   {RF_PORT}  (physical, RPHY Upstream Physical Interface)")
    print(f"  LogicalCh: {LOGICAL_CH}  {'(any — no pin)' if LOGICAL_CH == 0 else '(RPHY OFDMA Upstream)'}")
    print(f"  TFTP:      {TFTP_IP}")
    print(f"  Mode:      freeRunning  duration={FREERUN_DURATION}ms  repeat={REPEAT_PERIOD}µs")
    print(f"  Indexes:   {', '.join(IDX_CANDIDATES)}")
    print("=" * 60)

    selected_idx: str | None = None
    try:
        check_capability()
        provision_bdt()
        selected_idx = configure_utsc()
        if not selected_idx:
            print("\nStopping before trigger/poll because UTSC config row is unavailable.")
            sys.exit(2)
        trigger(selected_idx)
        poll_status(selected_idx)
    except KeyboardInterrupt:
        print("\n\nInterrupted — sending abort")
        if selected_idx:
            snmpset(f"{CTRL_BASE}{selected_idx}", "i", 2)
        sys.exit(1)


if __name__ == "__main__":
    main()
