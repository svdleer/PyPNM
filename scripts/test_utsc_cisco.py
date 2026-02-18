#!/usr/bin/env python3
"""
UTSC (Upstream Triggered Spectrum Capture) test script.

Vendor-aware provisioning:
  - Cisco cBR-8: BDT destroy/createAndGo, UTSC destroy/createAndGo
  - E6000/other: BDT and UTSC rows pre-exist, set params directly

Flow:
  0. sysDescr check -> detect Cisco vs other vendor
  1. BDT: provision TFTP destination (Cisco: destroy/createAndGo)
  2. UTSC: configure row (Cisco: destroy/createAndGo)
  3. Trigger: InitiateTest=1
  4. Poll MeasStatus until sampleReady

OIDs (DOCS-PNM-MIB):
  docsPnmBulkDataTransferCfgTable  .1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1
  docsPnmCmtsUtscCfgTable          .1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1
  docsPnmCmtsUtscCtrlTable         .1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1
  docsPnmCmtsUtscStatusTable       .1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1

Usage:
  python3 test_utsc_cisco.py
"""

import json
import os
import subprocess
import sys
import time

# ============================================================
# CONFIGURATION LOADING
# ============================================================

def load_config():
    """Load configuration from lab-config.json and pypnm_system.json"""
    config = {
        'cmts_ip': '172.16.6.202',  # Default
        'snmp_read': 'public',
        'snmp_write': 'private',
        'tftp_ip': '172.16.6.101',  # Default TFTP
        'tftp_ip_lab_cisco': '172.22.147.18',  # Lab-specific for Cisco
    }
    
    # Try to load lab-config.json (for lab environment)
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
                        print(f"  Loaded lab config from: {path}")
                        break
            except Exception as e:
                print(f"  Warning: Could not load {path}: {e}")
    
    # Try to load pypnm_system.json (for TFTP settings)
    system_config_paths = [
        '/Users/silvester/PythonDev/Git/PyPNMGui/config/pypnm_system.json',
        '../PyPNMGui/config/pypnm_system.json',
        '../../PyPNMGui/config/pypnm_system.json',
    ]
    for path in system_config_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    sys_cfg = json.load(f)
                    if 'PnmBulkDataTransfer' in sys_cfg:
                        tftp_cfg = sys_cfg['PnmBulkDataTransfer'].get('tftp', {})
                        config['tftp_ip'] = tftp_cfg.get('ip_v4', config['tftp_ip'])
                        print(f"  Loaded system config from: {path}")
                        break
            except Exception as e:
                print(f"  Warning: Could not load {path}: {e}")
    
    return config

# Load configuration
print("Loading configuration...")
CONFIG = load_config()

# ============================================================
# CONFIGURATION
# ============================================================

CMTS_IP = CONFIG['cmts_ip']
SNMP_READ = CONFIG['snmp_read']
SNMP_WRITE = CONFIG['snmp_write']

# TFTP destination (will be set per vendor in main())
TFTP_IP = CONFIG['tftp_ip']
TFTP_IP_HEX = ""  # Will be calculated
TFTP_URI = ""  # Will be calculated
TFTP_PORT = 69

# BDT row index
BDT_ROW = 1

# UTSC target
IF_INDEX = 488046               # Cable1/0/0-upstream6 (OFDMA)
CFG_INDEX = 1

# UTSC capture parameters (same as E6000 _configure_utsc defaults)
TRIGGER_MODE = 2                # 2=freeRunning
CENTER_FREQ = 16400000          # Hz
SPAN = 6400000                  # Hz
NUM_BINS = 1024
AVG_NUMBER = 245
OUTPUT_FORMAT = 1               # 1=fftPower (E6000 uses 5=fftAmplitude)
WINDOW = 3                      # 3=hann (E6000 uses 4=blackmanHarris)
REPEAT_PERIOD = 25000           # us (E6000 uses 50001)
FREE_RUN_DURATION = 5000        # ms (E6000 uses 600000)
TRIGGER_COUNT = 1
FILENAME = "utsc_spectrum"
CM_MAC = None

# Polling
POLL_INTERVAL = 3
POLL_TIMEOUT = 120

# SNMP remote execution
SNMP_PREFIX = (
    'ssh labthingy'
    '"docker exec pypnm-agent-lab {cmd}"'
)

# ============================================================
# OIDs
# ============================================================

PNM = "1.3.6.1.4.1.4491.2.1.27"
SYS_DESCR = "1.3.6.1.2.1.1.1.0"

# docsPnmBulkDataTransferCfgTable
BDT = f"{PNM}.1.1.3.1.1"

# docsPnmCmtsUtscCfgTable
UTSC = f"{PNM}.1.3.10.2.1"

# docsPnmCmtsUtscCtrlTable
UTSC_CTRL = f"{PNM}.1.3.10.3.1.1"

# docsPnmCmtsUtscStatusTable
UTSC_STATUS = f"{PNM}.1.3.10.4.1.1"

# Row suffix
SFX = f"{IF_INDEX}.{CFG_INDEX}"

# Named OID columns
BDT_COLS = {
    "DestHostname":       (f"{BDT}.2", "s"),
    "DestHostIpAddrType": (f"{BDT}.3", "i"),
    "DestHostIpAddress":  (f"{BDT}.4", "x"),
    "DestPort":           (f"{BDT}.5", "u"),
    "DestBaseUri":        (f"{BDT}.6", "s"),
    "Protocol":           (f"{BDT}.7", "i"),
    "LocalStore":         (f"{BDT}.8", "i"),
    "RowStatus":          (f"{BDT}.9", "i"),
}

UTSC_COLS = {
    "LogicalChIfIndex":   (f"{UTSC}.2",  "i"),
    "TriggerMode":        (f"{UTSC}.3",  "i"),
    "CmMacAddr":          (f"{UTSC}.6",  "x"),
    "CenterFreq":         (f"{UTSC}.8",  "u"),
    "Span":               (f"{UTSC}.9",  "u"),
    "NumBins":            (f"{UTSC}.10", "u"),
    "AvgNumber":          (f"{UTSC}.11", "u"),
    "Filename":           (f"{UTSC}.12", "s"),
    "QualifyCenterFreq":  (f"{UTSC}.13", "u"),
    "QualifyBw":       tuple[bool, bool]:
    """Query sysDescr to detect if CMTS is Cisco cBR-8.
    
    Returns:
        (is_cisco, is_lab): True if Cisco, True if lab environment
    """
    step("0. Vendor Detection (sysDescr)")
    raw = snmpget(SYS_DESCR)
    print(f"  sysDescr = {raw}")
    descr_lower = raw.lower() if raw else ""
    is_cisco = 'cisco' in descr_lower or 'cbr' in descr_lower
    
    # Detect lab environment (using specific lab CMTS IP)
    is_lab = CMTS_IP in ['172.16.6.212', '172.16.6.202']
    
    if is_cisco:
        print("  -> Cisco cBR-8 detected: will use destroy/createAndGo")
        if is_lab:
            print("  -> Lab environment: will use lab TFTP server")
    else:
        print("  -> Non-Cisco CMTS: will set params directly on existing rows")
    
    return is_cisco, is_lab


def configure_tftp_for_vendor(is_cisco: bool, is_lab: bool):
    """Configure TFTP settings based on vendor and environment.
    
    Args:
        is_cisco: True if Cisco CMTS
        is_lab: True if lab environment
    """
    global TFTP_IP, TFTP_IP_HEX, TFTP_URI
    
    # Cisco in lab uses special TFTP server
    if is_cisco and is_lab:
        TFTP_IP = CONFIG['tftp_ip_lab_cisco']
    else:
        TFTP_IP = CONFIG['tftp_ip']
    
    # Calculate hex representation
    octets = TFTP_IP.split('.')
    TFTP_IP_HEX = ''.join(f'{int(o):02X}' for o in octets)
    TFTP_URI = f"tftp://{TFTP_IP}/"
    
    print(f"  TFTP Server: {TFTP_IP} (hex: {TFTP_IP_HEX})")
    print(f"  TFTP URI: {TFTP_URI}")


# ============================================================
# SNMP
# ============================================================

def run_snmp(cmd: str) -> str:
    full_cmd = SNMP_PREFIX.format(cmd=cmd) if SNMP_PREFIX else cmd
    r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30)
    out = r.stdout.strip()
    if r.returncode != 0 and r.stderr.strip():
        for line in r.stderr.strip().splitlines():
            if "Cannot find module" not in line and "MIB search" not in line:
                print(f"  STDERR: {line}")
    return out


def snmpget(oid: str) -> str:
    return run_snmp(f"snmpget -v2c -c {SNMP_READ} -Ov {CMTS_IP} {oid}")


def snmpwalk(oid: str) -> str:
    return run_snmp(f"snmpwalk -v2c -c {SNMP_READ} {CMTS_IP} {oid}")


def snmpset(oid: str, t: str, v) -> str:
    return run_snmp(f"snmpset -v2c -c {SNMP_WRITE} {CMTS_IP} {oid} {t} {v}")


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
# Vendor Detection
# ============================================================

def detect_vendor() -> bool:
    """Query sysDescr to detect if CMTS is Cisco cBR-8.
    
    Returns True if Cisco, False otherwise.
    """
    step("0. Vendor Detection (sysDescr)")
    raw = snmpget(SYS_DESCR)
    print(f"  sysDescr = {raw}")
    descr_lower = raw.lower() if raw else ""
    is_cisco = 'cisco' in descr_lower or 'cbr' in descr_lower
    if is_cisco:
        print("  -> Cisco cBR-8 detected: will use destroy/createAndGo")
    else:
        print("  -> Non-Cisco CMTS: will set params directly on existing rows")
    return is_cisco


# ============================================================
# BDT Table
# ============================================================

def provision_bdt(is_cisco: bool):
    """Provision BDT row.
    
    Cisco: destroy -> createAndGo -> set columns.
    Other: set columns directly on existing row.
    """
    step(f"1. Provision BDT Row {BDT_ROW}")

    oid_rs, t_rs = BDT_COLS["RowStatus"]

    if is_cisco:
        # Destroy existing row
        print(f"  docsPnmBulkDataTransferCfgRowStatus.{BDT_ROW} = destroy(6)")
        snmpset(f"{oid_rs}.{BDT_ROW}", t_rs, 6)
        time.sleep(2)

        # CreateAndGo(4)
        print(f"  docsPnmBulkDataTransferCfgRowStatus.{BDT_ROW} = createAndGo(4)")
        r = snmpset(f"{oid_rs}.{BDT_ROW}", t_rs, 4)
        print(f"    {r}")
        time.sleep(1)

    # Set columns
    columns = [
        ("DestHostIpAddrType", 1),              # ipv4(1)
        ("DestHostIpAddress",  TFTP_IP_HEX),    # hex IP
        ("DestBaseUri",        TFTP_URI),        # tftp://ip/
    ]
    # Protocol=1 (tftp): Cisco defaults it from createAndGo (SET causes genError);
    # other vendors need it set explicitly
    if not is_cisco:
        columns.append(("Protocol", 1))

    for col_name, value in columns:
        oid, t = BDT_COLS[col_name]
        print(f"  docsPnmBulkDataTransferCfg{col_name}.{BDT_ROW} = {value}")
        r = snmpset(f"{oid}.{BDT_ROW}", t, value)
        print(f"    {r}")


def verify_bdt():
    """Walk and verify BDT row matches expected values."""
    step(f"2. Verify BDT Row {BDT_ROW}")
    col_names = [
        "DestHostname", "DestHostIpAddrType", "DestHostIpAddress",
        "DestPort", "DestBaseUri", "Protocol", "LocalStore", "RowStatus"
    ]
    for col_name in col_names:
        oid, _ = BDT_COLS[col_name]
        r = snmpget(f"{oid}.{BDT_ROW}")
        print(f"  docsPnmBulkDataTransferCfg{col_name}.{BDT_ROW} = {r}")


# ============================================================
# UTSC Config
# ============================================================

def configure_utsc(is_cisco: bool):
    """Configure UTSC row.

    Cisco cBR-8: destroy -> createAndGo -> set params.
    Other vendors: set params directly on existing row.
    """
    step(f"3. Configure UTSC Row {SFX}")

    oid_rs, t_rs = UTSC_COLS["RowStatus"]

    if is_cisco:
        # Destroy any existing row
        print(f"  docsPnmCmtsUtscCfgRowStatus.{SFX} = destroy(6)")
        snmpset(f"{oid_rs}.{SFX}", t_rs, 6)
        time.sleep(2)

        # CreateAndGo(4)
        print(f"  docsPnmCmtsUtscCfgRowStatus.{SFX} = createAndGo(4)")
        r = snmpset(f"{oid_rs}.{SFX}", t_rs, 4)
        print(f"    {r}")
        time.sleep(1)

    # Set parameters — same order as E6000 _configure_utsc()
    params = [
        ("LogicalChIfIndex",  IF_INDEX),
        ("TriggerMode",       TRIGGER_MODE),
        ("NumBins",           NUM_BINS),
        ("CenterFreq",        CENTER_FREQ),
        ("Span",              SPAN),
        ("OutputFormat",       OUTPUT_FORMAT),
        ("Window",            WINDOW),
        ("FreeRunDuration",   FREE_RUN_DURATION),
        ("RepeatPeriod",      REPEAT_PERIOD),
        ("Filename",          FILENAME),
        ("DestinationIndex",  BDT_ROW),
    ]

    for col_name, value in params:
        oid, t = UTSC_COLS[col_name]
        print(f"  docsPnmCmtsUtscCfg{col_name}.{SFX} = {value}")
        r = snmpset(f"{oid}.{SFX}", t, value)
        print(f"    {r}")
        time.sleep(0.1)


def verify_utsc():
    """Verify UTSC config row."""
    step(f"4. Verify UTSC Row {SFX}")
    check_cols = [
        "LogicalChIfIndex", "TriggerMode", "CenterFreq", "Span",
        "NumBins", "OutputFormat", "Window", "RepeatPeriod",
        "FreeRunDuration", "Filename", "DestinationIndex", "RowStatus"
    ]
    for col_name in check_cols:
        oid, _ = UTSC_COLS[col_name]
        r = snmpget(f"{oid}.{SFX}")
        print(f"  docsPnmCmtsUtscCfg{col_name}.{SFX} = {r}")


def trigger_utsc():
    """InitiateTest=1."""
    step("5. Trigger UTSC (InitiateTest=1)")
    r = snmpset(f"{UTSC_CTRL}.{SFX}", "i", 1)
    print(f"  docsPnmCmtsUtscCtrlInitiateTest.{SFX} = 1 (start)")
    print(f"    {r}")


def poll_status():
    """Poll MeasStatus until sampleReady."""
    step("6. Poll MeasStatus")
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > POLL_TIMEOUT:
            print(f"\n  TIMEOUT after {POLL_TIMEOUT}s!")
            return False
        raw = snmpget(f"{UTSC_STATUS}.{SFX}")
        s = val(raw)
        name = MEAS_STATUS.get(s, "unknown")
        print(f"  [{elapsed:5.1f}s] docsPnmCmtsUtscStatusMeasStatus.{SFX} = {s} ({name})")
        if s == 4:
            print("\n  sampleReady!")
            return True
        elif s == 7:
            print("\n  sampleTruncated")
            return True
        elif s in (5, 6):
            print(f"\n  {name}!")
            return False
        time.sleep(POLL_INTERVAL)


def abort_utsc():
    """Abort capture."""
    step("ABORT Capture")
    r = snmpset(f"{UTSC_CTRL}.{SFX}", "i", 2)
    print(f"  docsPnmCmtsUtscCtrlInitiateTest.{SFX} = 2 (abort)")
    print(f"    {r}")


def show_resulTrigger:   {TRIGGER_MODE} (freeRunning)")
    print(f"  Count:     {TRIGGER_COUNT}")
    print("=" * 60)

    try:
        is_cisco, is_lab = detect_vendor()  # 0  sysDescr check
        configure_tftp_for_vendor(is_cisco, is_lab)  # Set TFTP based on vendor/env
        print(f"  BDT row:   {BDT_ROW} -> {TFTP_URI}")
    print(f"  docsPnmCmtsUtscStatusMeasStatus.{SFX} = {r}  ({MEAS_STATUS.get(s, '?')})")

    print("  --- UTSC Config ---")
    for col in ["DestinationIndex", "RowStatus"]:
        oid, _ = UTSC_COLS[col]
        r = snmpget(f"{oid}.{SFX}")
        print(f"  docsPnmCmtsUtscCfg{col}.{SFX} = {r}")

    print("  --- BDT Row ---")
    for col in ["DestHostname", "DestHostIpAddrType", "DestHostIpAddress",
                "DestPort", "DestBaseUri", "Protocol", "LocalStore", "RowStatus"]:
        oid, _ = BDT_COLS[col]
        r = snmpget(f"{oid}.{BDT_ROW}")
        print(f"  docsPnmBulkDataTransferCfg{col}.{BDT_ROW} = {r}")


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("  UTSC Test - Vendor-Aware Provisioning")
    print(f"  CMTS:      {CMTS_IP}")
    print(f"  ifIndex:   {IF_INDEX}")
    print(f"  BDT row:   {BDT_ROW} -> {TFTP_URI}")
    print(f"  Trigger:   {TRIGGER_MODE} (freeRunning)")
    print(f"  Count:     {TRIGGER_COUNT}")
    print("=" * 60)

    try:
        is_cisco = detect_vendor()  # 0  sysDescr check
        provision_bdt(is_cisco)     # 1  BDT row
        verify_bdt()                # 2  Verify BDT row
        configure_utsc(is_cisco)    # 3  UTSC row
        verify_utsc()               # 4  Verify UTSC row
        trigger_utsc()              # 5  InitiateTest=1
        success = poll_status()     # 6  Poll MeasStatus
        show_results()              # 7  Final state

        if success:
            print("\n  Check TFTP server for files!")
        else:
            print("\n  Capture did not complete successfully.")

    except KeyboardInterrupt:
        print("\n\nInterrupted!")
        abort_utsc()
        sys.exit(1)


if __name__ == "__main__":
    main()
