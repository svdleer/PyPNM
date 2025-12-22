#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026
"""
UTSC provisioning script — CommScope E6000, Casa 100G, Cisco cBR-8.

Detects vendor via sysDescr and applies the correct row lifecycle,
constraint enforcement and trigger flow for each platform.

CommScope E6000
  - Rows are pre-provisioned per RF port by the CMTS at boot.
  - Probe cfg_index 1-3 for a row matching TriggerMode; write in place.
  - If no row found: destroy + createAndGo.
  - CORE/C-CCAP (ifDescr 'us-conn'): window must be rectangular(2).
  - I-CCAP: window 2-5 supported.
  - Repeat period 50ms-1000ms; freerun 1s-600s; max 250 files per run.
  - OutputFormat 1-5 supported; fast repeat (<50ms) requires fftPower(2).
  - BDT: docsPnmBulkDataTransferCfgTable (1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1)

Casa 100G
  - Same in-place write flow as E6000.
  - Repeat period >= 100ms; freerun 120s-300s; files = freerun/repeat <= 300.
  - BDT: docsPnmCcapBulkDataControlTable (1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1)
    Set DestIpAddr, DestPath, UploadControl=autoUpload(3), PnmTestSelector bit8.

Cisco cBR-8
  - No pre-provisioned rows. Destroy any existing row, then createAndGo(4).
  - OutputFormat: timeIQ(1), fftPower(2), fftIQ(4) only.
  - RepeatPeriod <= FreeRunDuration.
  - Cisco uploads directly to TFTP — BDT table not used.
  - sysDescr is hex-encoded; script decodes it automatically.

CommScope EVO vCCAP
  - Detected and rejected: UTSC capability bits are all zero on firmware 10.10.0.
  - Use provision_utsc_evo.py to document the failure mode.

Usage:
    python3 provision_utsc.py <cmts_ip> <rf_port_ifindex> [cfg_index]

    python3 provision_utsc.py 172.16.6.202 488046         # Cisco cBR-8
    python3 provision_utsc.py 172.16.6.101 150994984 1    # E6000
    python3 provision_utsc.py 172.16.6.160 838860800 1    # Casa 100G

Environment variables (override defaults):
    SNMP_READ       SNMP read community  (default: public)
    SNMP_WRITE      SNMP write community (default: private)
    TFTP_IP         TFTP server IP       (default: 172.16.6.101)
    TFTP_PATH       TFTP upload path     (default: ./)
    SSH_HOST        Jump server hostname (default: access-engineering.nl)
    AGENT_CMD       Docker exec prefix   (default: docker exec pypnm-agent-lab)
"""

import os
import re
import subprocess
import sys
import time

# ============================================================
# Configuration
# ============================================================

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

CMTS_IP    = sys.argv[1]
RF_PORT    = int(sys.argv[2])
CFG_INDEX  = int(sys.argv[3]) if len(sys.argv) > 3 else 1

SNMP_READ  = os.environ.get("SNMP_READ",  "public")
SNMP_WRITE = os.environ.get("SNMP_WRITE", "private")
TFTP_IP    = os.environ.get("TFTP_IP",    "172.16.6.101")
TFTP_IP_CCAP  = os.environ.get("TFTP_IP_CCAP",  "172.22.147.18")  # CCAP (Casa/Cisco) use separate TFTP reachable from device
TFTP_PATH  = os.environ.get("TFTP_PATH",  "./")
SSH_HOST   = os.environ.get("SSH_HOST",   "access-engineering.nl")
AGENT_CMD  = os.environ.get("AGENT_CMD",  "docker exec pypnm-agent-lab")

# Capture defaults (overridden per vendor below)
TRIGGER_MODE     = 2        # freeRunning
CENTER_FREQ      = 45000000 # 45 MHz — span/2=40MHz, so lower edge=5MHz (valid for DOCSIS US)
SPAN             = 80000000 # 80 MHz
NUM_BINS         = 800   # E6000 non-TimeIQ valid: 200/400/800/1600/3200
OUTPUT_FORMAT    = 2        # fftPower — safe default for all vendors
WINDOW           = 2        # rectangular
REPEAT_PERIOD    = 100000   # 100 ms (µs)
FREERUN_DURATION = 120000   # 120 s (ms)
TRIGGER_COUNT    = 1
FILENAME         = "utsc_capture"
BDT_ROW          = 1

TFTP_HEX = "".join(f"{int(o):02X}" for o in TFTP_IP.split("."))

# RowStatus values
RS_ACTIVE      = 1
RS_CREATE_AND_GO  = 4
RS_CREATE_WAIT = 5
RS_DESTROY     = 6

# OIDs
OID_SYS_DESCR       = "1.3.6.1.2.1.1.1.0"
OID_IF_DESCR        = "1.3.6.1.2.1.2.2.1.2"
OID_UTSC_CFG        = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
OID_UTSC_CTRL       = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1"
OID_UTSC_STAT       = "1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1"
OID_UTSC_TRIG_MODE  = f"{OID_UTSC_CFG}.3"

# E6000 BDT table (docsPnmBulkDataTransferCfgTable)
OID_BDT_E6000       = "1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1"

# Casa BDT table (docsPnmCcapBulkDataControlTable)
OID_BDT_CASA        = "1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1"

MEAS_STATUS = {
    1: "other", 2: "inactive", 3: "triggered",
    4: "sampleReady", 5: "error", 6: "measurementBusy", 7: "sampleTruncated",
}

POLL_INTERVAL = 3
POLL_TIMEOUT  = 300

# ============================================================
# SNMP helpers
# ============================================================

def _run(cmd: str) -> str:
    full = f'ssh {SSH_HOST} "{AGENT_CMD} {cmd}"'
    r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=20)
    out = r.stdout.strip()
    if r.returncode != 0:
        stderr = r.stderr.strip()
        # notWritable/noAccess are harmless on DestinationIndex (Casa) and Filename (Cisco)
        if "notWritable" in stderr or "noAccess" in stderr:
            return out
        for line in stderr.splitlines():
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
    print(f"\n{'='*60}\n  {name}\n{'='*60}")


# ============================================================
# Vendor detection
# ============================================================

def detect_vendor() -> tuple[str, str]:
    """
    Returns (vendor, raw_sysdescr).
    vendor: 'e6000' | 'casa' | 'cisco' | 'evo' | 'unknown'
    """
    raw = snmpget(OID_SYS_DESCR)
    # Strip OID prefix if present
    if " = " in raw:
        raw = raw.split(" = ", 1)[1].strip()
    # Cisco returns hex-encoded OctetString
    if raw.upper().startswith("0X"):
        try:
            raw = bytes.fromhex(raw[2:]).decode("utf-8", errors="replace")
        except Exception:
            pass
    upper = raw.upper()
    if "DCTS VCCAP" in upper:
        return "evo", raw
    if "CASA" in upper:
        return "casa", raw
    if "ARRIS" in upper or "COMMSCOPE" in upper:
        return "e6000", raw
    if "CISCO" in upper:
        return "cisco", raw
    return "unknown", raw


def is_arris_core(rf_port: int) -> bool:
    """
    E6000 CORE/C-CCAP carries 'us-conn' in ifDescr and only supports rectangular(2).
    I-CCAP does not and supports windows 2-5.
    """
    raw = snmpget(f"{OID_IF_DESCR}.{rf_port}")
    if " = " in raw:
        raw = raw.split(" = ", 1)[1].strip()
    return "us-conn" in raw.lower()


# ============================================================
# Row lifecycle
# ============================================================

def find_row(rf_port: int, trigger_mode: int) -> int | None:
    """
    Probe cfg_index 1-3 for an existing row matching trigger_mode.
    Returns cfg_index if found, else None.
    """
    for probe in range(1, 4):
        raw = snmpget(f"{OID_UTSC_TRIG_MODE}.{rf_port}.{probe}")
        if "No Such" in raw or raw == "":
            continue
        try:
            if val(raw) == trigger_mode:
                print(f"  found row at cfg_index={probe} (TriggerMode={trigger_mode})")
                return probe
        except Exception:
            pass
    return None


def destroy_row(rf_port: int, cfg_index: int):
    print(f"  RowStatus.{rf_port}.{cfg_index} = destroy(6)")
    snmpset(f"{OID_UTSC_CFG}.21.{rf_port}.{cfg_index}", "i", RS_DESTROY)
    time.sleep(2)


def create_and_go(rf_port: int, cfg_index: int) -> bool:
    print(f"  RowStatus.{rf_port}.{cfg_index} = createAndGo(4)")
    r = snmpset(f"{OID_UTSC_CFG}.21.{rf_port}.{cfg_index}", "i", RS_CREATE_AND_GO)
    print(f"    {r}")
    if "commitFailed" in r or "wrongValue" in r:
        print(f"  ERROR: createAndGo rejected — {r}")
        return False
    time.sleep(1)
    return True


# ============================================================
# Constraint enforcement
# ============================================================

def apply_casa_constraints(repeat_us: int, freerun_ms: int) -> tuple[int, int]:
    """Casa 100G / EVO: repeat >= 100ms, freerun 120-300s, files <= 300."""
    if repeat_us < 100000:
        print(f"  [clamp] repeat_period {repeat_us} -> 100000 µs (Casa min 100ms)")
        repeat_us = 100000
    if freerun_ms < 120000:
        print(f"  [clamp] freerun_duration {freerun_ms} -> 120000 ms (Casa min 120s)")
        freerun_ms = 120000
    if freerun_ms > 300000:
        print(f"  [clamp] freerun_duration {freerun_ms} -> 300000 ms (Casa max 300s)")
        freerun_ms = 300000
    min_repeat = ((freerun_ms + 299) // 300) * 1000
    if repeat_us < min_repeat:
        print(f"  [clamp] repeat_period raised {repeat_us} -> {min_repeat} µs (Casa max 300 files)")
        repeat_us = min_repeat
    return repeat_us, freerun_ms


def apply_e6000_constraints(repeat_us: int, freerun_ms: int, output_fmt: int, window: int, core: bool, num_bins: int = 800) -> tuple[int, int, int, int, int]:
    """E6000: repeat 50ms-1000ms, freerun <= 600s, files <= 250."""
    if repeat_us < 50001:
        print(f"  [clamp] repeat_period {repeat_us} -> 50001 µs (E6000 min >50ms, strictly)")
        repeat_us = 50001
    if repeat_us > 1000000:
        print(f"  [clamp] repeat_period {repeat_us} -> 1000000 µs (E6000 max 1000ms)")
        repeat_us = 1000000
    if freerun_ms <= 0:
        freerun_ms = 60000
    if freerun_ms > 600000:
        print(f"  [clamp] freerun_duration {freerun_ms} -> 600000 ms (E6000 max 600s)")
        freerun_ms = 600000
    # max 250 files per run (MaxResultsPerFile is read-only 1 on E6000)
    max_freerun_for_250 = 250 * (repeat_us // 1000)
    if freerun_ms > max_freerun_for_250:
        print(f"  [clamp] freerun_duration {freerun_ms} -> {max_freerun_for_250} ms (E6000 max 250 files)")
        freerun_ms = max_freerun_for_250
    # snap num_bins to nearest valid value for non-TimeIQ
    if output_fmt != 1:
        valid_bins = (200, 400, 800, 1600, 3200)
        if num_bins not in valid_bins:
            snapped = min(valid_bins, key=lambda x: abs(x - num_bins))
            print(f"  [clamp] num_bins {num_bins} -> {snapped} (E6000 non-TimeIQ: {valid_bins})")
            num_bins = snapped
    if core and window != 2:
        print(f"  [clamp] window {window} -> 2 (E6000 CORE/C-CCAP: rectangular only)")
        window = 2
    elif not core and window not in (2, 3, 4, 5):
        print(f"  [clamp] window {window} -> 2 (E6000 I-CCAP: supported 2-5)")
        window = 2
    return repeat_us, freerun_ms, output_fmt, window, num_bins


def apply_cisco_constraints(repeat_us: int, freerun_ms: int, output_fmt: int) -> tuple[int, int, int]:
    """Cisco cBR-8: output_format 1/2/4 only, repeat <= freerun."""
    if output_fmt not in (1, 2, 4):
        print(f"  [clamp] output_format {output_fmt} -> 2 (Cisco: timeIQ(1)/fftPower(2)/fftIQ(4) only)")
        output_fmt = 2
    if freerun_ms <= 0:
        freerun_ms = 5000
    if repeat_us > freerun_ms * 1000:
        repeat_us = freerun_ms * 1000
        print(f"  [clamp] repeat_period clamped to freerun_duration ({repeat_us} µs)")
    return repeat_us, freerun_ms, output_fmt


# ============================================================
# BDT configuration
# ============================================================

def configure_bdt_cisco(row: int):
    """Cisco BDT: docsPnmBulkDataTransferCfgTable.

    Cisco defaults Protocol=tftp from createAndGo — setting it causes genError.
    Uses a separate TFTP server reachable from the cBR-8 (TFTP_IP_CCAP).
    """
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
        (f"{OID_BDT_E6000}.3.{row}", "i", 1,       "DestHostIpAddrType = ipv4(1)"),
        (f"{OID_BDT_E6000}.4.{row}", "x", tftp_hex, f"DestHostIpAddress  = {tftp}"),
        (f"{OID_BDT_E6000}.6.{row}", "s", f"tftp://{tftp}/", f"DestBaseUri        = tftp://{tftp}/"),
        # Protocol: NOT set on Cisco — createAndGo defaults it; explicit SET causes genError
    ]
    for oid, t, v, desc in fields:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")


def configure_bdt_e6000(row: int):
    """E6000 BDT: docsPnmBulkDataTransferCfgTable.

    Row may already be active from a previous run — don't destroy it first.
    Just write the fields directly; if row doesn't exist yet try createAndWait.
    """
    step(f"BDT row {row} — E6000 (docsPnmBulkDataTransferCfgTable) — TFTP {TFTP_IP}")
    # Check current RowStatus — only createAndWait if the row doesn't exist yet
    rs_raw = snmpget(f"{OID_BDT_E6000}.9.{row}")
    if "No Such" in rs_raw or rs_raw == "":
        print(f"  RowStatus.{row} = createAndWait(5)")
        r = snmpset(f"{OID_BDT_E6000}.9.{row}", "i", RS_CREATE_WAIT)
        print(f"    {r}")
        time.sleep(0.5)
    else:
        print(f"  row {row} exists ({rs_raw.strip()}) — writing fields in place")
    fields = [
        (f"{OID_BDT_E6000}.3.{row}", "i", 1,        "DestHostIpAddrType = ipv4(1)"),
        (f"{OID_BDT_E6000}.4.{row}", "x", TFTP_HEX, f"DestHostIpAddress  = {TFTP_IP}"),
        (f"{OID_BDT_E6000}.6.{row}", "s", f"tftp://{TFTP_IP}/", f"DestBaseUri        = tftp://{TFTP_IP}/"),
        (f"{OID_BDT_E6000}.7.{row}", "i", 1,        "Protocol           = tftp(1)"),
    ]
    for oid, t, v, desc in fields:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")
    print(f"  RowStatus.{row} = active(1)")
    r = snmpset(f"{OID_BDT_E6000}.9.{row}", "i", RS_ACTIVE)
    print(f"    {r}")


def configure_bdt_casa(row: int, tftp_ip: str = None):
    """Casa / Cisco CCAP: docsPnmCcapBulkDataControlTable — UploadControl=autoUpload(3), PnmTestSelector=UTSC bit."""
    if tftp_ip is None:
        tftp_ip = TFTP_IP_CCAP
    tftp_hex = "".join(f"{int(o):02X}" for o in tftp_ip.split("."))
    step(f"BDT CCAP row {row} — docsPnmCcapBulkDataControlTable — TFTP {tftp_ip}")
    # DestIpAddrType = ipv4(1)
    r = snmpset(f"{OID_BDT_CASA}.2.{row}", "i", 1)
    print(f"  DestIpAddrType = ipv4(1)  {r}")
    # DestIpAddr (hex)
    r = snmpset(f"{OID_BDT_CASA}.3.{row}", "x", tftp_hex)
    print(f"  DestIpAddr     = {tftp_ip}  {r}")
    # DestPath
    r = snmpset(f"{OID_BDT_CASA}.4.{row}", "s", TFTP_PATH)
    print(f"  DestPath       = {TFTP_PATH}  {r}")
    # UploadControl = autoUpload(3)
    r = snmpset(f"{OID_BDT_CASA}.5.{row}", "i", 3)
    print(f"  UploadControl  = autoUpload(3)  {r}")
    # PnmTestSelector: bit8 = usTriggeredSpectrumCapture
    # snmpset hex type 'x' expects 0xNNNN format
    r = snmpset(f"{OID_BDT_CASA}.6.{row}", "x", "0x0080")
    print(f"  PnmTestSelector= 0x0080 (UTSC)  {r}")


# ============================================================
# UTSC configure
# ============================================================

def configure_utsc(
    rf_port: int,
    cfg_index: int,
    vendor: str,
    repeat_us: int,
    freerun_ms: int,
    output_fmt: int,
    window: int,
    num_bins: int,
):
    idx = f".{rf_port}.{cfg_index}"
    step(f"UTSC configure  rf_port={rf_port}  cfg_index={cfg_index}  vendor={vendor}")

    # LogicalChIfIndex: Cisco sets it to the rf_port ifindex itself;
    # Casa/E6000 set it to 0 (any channel)
    logical_ch = rf_port if vendor == "cisco" else 0
    params = [
        (f"{OID_UTSC_CFG}.2{idx}",  "i", logical_ch,   f"LogicalChIfIndex   = {logical_ch}"),
        (f"{OID_UTSC_CFG}.3{idx}",  "i", TRIGGER_MODE,  f"TriggerMode        = {TRIGGER_MODE} (freeRunning)"),
        (f"{OID_UTSC_CFG}.8{idx}",  "u", CENTER_FREQ,   f"CenterFreq         = {CENTER_FREQ // 1_000_000} MHz"),
        (f"{OID_UTSC_CFG}.9{idx}",  "u", SPAN,          f"Span               = {SPAN // 1_000_000} MHz"),
        (f"{OID_UTSC_CFG}.10{idx}", "u", num_bins,       f"NumBins            = {num_bins}"),
        (f"{OID_UTSC_CFG}.17{idx}", "i", output_fmt,    f"OutputFormat       = {output_fmt}"),
        (f"{OID_UTSC_CFG}.16{idx}", "i", window,        f"WindowFunction     = {window}"),
        (f"{OID_UTSC_CFG}.19{idx}", "u", freerun_ms,    f"FreeRunDuration    = {freerun_ms} ms ({freerun_ms // 1000} s)"),
        (f"{OID_UTSC_CFG}.18{idx}", "u", repeat_us,     f"RepeatPeriod       = {repeat_us} µs ({repeat_us // 1000} ms)"),
        (f"{OID_UTSC_CFG}.20{idx}", "u", TRIGGER_COUNT,  f"TriggerCount       = {TRIGGER_COUNT}"),
    ]
    # DestinationIndex: E6000 and Cisco only — Casa manages it internally, notWritable on in-place rows
    if vendor in ("e6000", "cisco") and BDT_ROW > 0:
        params.append((f"{OID_UTSC_CFG}.24{idx}", "u", BDT_ROW, f"DestinationIndex   = {BDT_ROW}"))
    # Filename: E6000 and Cisco; notWritable on Casa
    if vendor in ("e6000", "cisco"):
        params.append((f"{OID_UTSC_CFG}.12{idx}", "s", FILENAME, f"Filename           = {FILENAME}"))

    for oid, t, v, desc in params:
        print(f"  {desc}")
        r = snmpset(oid, t, v)
        print(f"    {r}")
        time.sleep(0.05)

    # Verify row is active after writes
    rs = snmpget(f"{OID_UTSC_CFG}.21{idx}")
    print(f"\n  RowStatus readback: {rs}")


# ============================================================
# Trigger + poll
# ============================================================

def trigger(rf_port: int, cfg_index: int):
    step(f"Trigger  InitiateTest=1  rf_port={rf_port}  cfg_index={cfg_index}")
    # Set RowStatus=active before InitiateTest — CMTS returns inconsistentValue otherwise.
    rs = snmpget(f"{OID_UTSC_CFG}.21.{rf_port}.{cfg_index}")
    if val(rs) != 1:
        print(f"  RowStatus={val(rs)} — setting active(1) before trigger")
        snmpset(f"{OID_UTSC_CFG}.21.{rf_port}.{cfg_index}", "i", RS_ACTIVE)
    r = snmpset(f"{OID_UTSC_CTRL}.{rf_port}.{cfg_index}", "i", 1)
    print(f"  {r}")


def poll(rf_port: int, cfg_index: int) -> bool:
    step("Poll MeasStatus")
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > POLL_TIMEOUT:
            print(f"\n  timeout after {POLL_TIMEOUT}s")
            return False
        raw = snmpget(f"{OID_UTSC_STAT}.{rf_port}.{cfg_index}")
        s = val(raw)
        name = MEAS_STATUS.get(s, "unknown")
        print(f"  [{elapsed:5.1f}s]  MeasStatus={s} ({name})")
        if s == 4:
            print("\n  sampleReady — check TFTP server")
            return True
        if s == 7:
            print("\n  sampleTruncated")
            return True
        if s in (5,):
            print(f"\n  error ({name})")
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
        print("\n  Unknown vendor — proceeding with E6000/Cisco defaults. Check results carefully.")

    # Resolve constraints per vendor
    repeat_us    = REPEAT_PERIOD
    freerun_ms   = FREERUN_DURATION
    output_fmt   = OUTPUT_FORMAT
    window       = WINDOW
    num_bins     = NUM_BINS
    core         = False

    if vendor in ("casa",):
        repeat_us, freerun_ms = apply_casa_constraints(repeat_us, freerun_ms)
        output_fmt = 5   # fftAmplitude — accepted on Casa
    elif vendor == "e6000":
        core = is_arris_core(RF_PORT)
        print(f"\n  E6000 subtype: {'CORE/C-CCAP (rectangular window only)' if core else 'I-CCAP (window 2-5)'}")
        repeat_us, freerun_ms, output_fmt, window, num_bins = apply_e6000_constraints(
            repeat_us, freerun_ms, output_fmt, window, core, num_bins
        )
    elif vendor == "cisco":
        repeat_us, freerun_ms, output_fmt = apply_cisco_constraints(repeat_us, freerun_ms, output_fmt)

    print(f"\n  repeat_period     = {repeat_us} µs ({repeat_us // 1000} ms)")
    print(f"  freerun_duration  = {freerun_ms} ms ({freerun_ms // 1000} s)")
    print(f"  output_format     = {output_fmt}")
    print(f"  window            = {window}")

    # BDT setup
    if vendor == "cisco":
        configure_bdt_cisco(BDT_ROW)
    elif vendor == "casa":
        configure_bdt_casa(BDT_ROW)
    elif vendor in ("e6000", "unknown"):
        configure_bdt_e6000(BDT_ROW)

    step(f"1. Row lifecycle  vendor={vendor}  rf_port={RF_PORT}")
    cfg_index = CFG_INDEX

    if vendor == "cisco":
        destroy_row(RF_PORT, cfg_index)
        if not create_and_go(RF_PORT, cfg_index):
            sys.exit(1)
    else:
        found = find_row(RF_PORT, TRIGGER_MODE)
        if found is not None:
            cfg_index = found
            print(f"  writing in place at cfg_index={cfg_index}")
        else:
            print(f"  no row found — destroy + createAndGo at cfg_index={cfg_index}")
            destroy_row(RF_PORT, cfg_index)
            if not create_and_go(RF_PORT, cfg_index):
                sys.exit(1)

    # Configure, trigger, poll
    configure_utsc(RF_PORT, cfg_index, vendor, repeat_us, freerun_ms, output_fmt, window, num_bins)

    try:
        trigger(RF_PORT, cfg_index)
        poll(RF_PORT, cfg_index)
    except KeyboardInterrupt:
        print("\n\nInterrupted")
        sys.exit(1)
    finally:
        print(f"\n  Stop  InitiateTest=2  rf_port={RF_PORT}  cfg_index={cfg_index}")
        r = snmpset(f"{OID_UTSC_CTRL}.{RF_PORT}.{cfg_index}", "i", 2)
        print(f"    {r}")


if __name__ == "__main__":
    main()
