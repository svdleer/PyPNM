#!/usr/bin/env python3
"""Quick E2E UTSC test - direct SNMP, no API dependency."""
import subprocess, time, os, sys

CMTS = "172.16.6.212"
COMM = "Z1gg0Sp3c1@l"
PORT = 1074864128

def snmp(cmd, oid, *args):
    c = ["snmp" + cmd, "-v2c", "-c", COMM, CMTS] + list(args) + [oid]
    r = subprocess.run(c, capture_output=True, text=True, timeout=10)
    return r.stdout.strip()

# 1. Stop
print("1. STOP")
print(snmp("set", f"DOCS-PNM-MIB::docsPnmCmtsUtscCtrlInitiateTest.{PORT}.1", "i", "2"))
time.sleep(1)

# 2. Current config
print("\n2. CONFIG")
cols = [(3,"TrigMode"),(8,"CenterFreq"),(9,"Span"),(10,"NumBins"),(11,"OutputFmt"),(12,"Window"),(14,"RepeatPeriod"),(15,"FreeRunDur"),(16,"TrigCount"),(19,"Filename"),(21,"RowStatus")]
for col, name in cols:
    oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.{col}.{PORT}.1"
    print(f"  {name}: {snmp('get', oid)}")

# 3. Configure
print("\n3. CONFIGURE")
sets = [
    (3, "i", "2"),
    (8, "u", "45000000"),
    (9, "u", "80000000"),
    (10, "u", "800"),
    (11, "i", "5"),
    (12, "i", "4"),
    (14, "u", "400000"),
    (15, "u", "600000"),
    (16, "u", "10"),
]
for col, typ, val in sets:
    oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.{col}.{PORT}.1"
    r = snmp("set", oid, typ, val)
    print(f"  col {col}: {r}")
time.sleep(1)

# 4. Verify
print("\n4. VERIFY")
for col, name in [(14,"RepeatPeriod"),(15,"FreeRunDur"),(19,"Filename")]:
    oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.{col}.{PORT}.1"
    print(f"  {name}: {snmp('get', oid)}")

# 5. Start
print("\n5. START")
print(snmp("set", f"DOCS-PNM-MIB::docsPnmCmtsUtscCtrlInitiateTest.{PORT}.1", "i", "1"))

# 6. Poll status
print("\n6. POLL STATUS")
for i in range(15):
    time.sleep(1)
    r = snmp("get", f"DOCS-PNM-MIB::docsPnmCmtsUtscCtrlMeasStatus.{PORT}.1")
    print(f"  {i+1}s: {r}")
    if "sampleReady" in r or "(4)" in r:
        print("  >>> SAMPLE READY!")
        break

# 7. Check files
print("\n7. FILES")
for d in ["/var/lib/tftpboot", "/var/lib/tftpboot/pnm/utsc"]:
    if os.path.exists(d):
        files = sorted([f for f in os.listdir(d) if "utsc" in f.lower()],
                       key=lambda f: os.path.getmtime(os.path.join(d,f)), reverse=True)[:5]
        print(f"  {d}: {files}")
    else:
        print(f"  {d}: NOT FOUND")
