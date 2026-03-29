#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Analyze agent enrichment logs to find IP-range success/failure patterns."""

import json
import re
import sys
import urllib.request
from collections import defaultdict

API_BASE = "http://localhost:8000"
LIMIT = 5000

def main():
    url = f"{API_BASE}/api/agents/logs?level=DEBUG&limit={LIMIT}"
    r = urllib.request.urlopen(url, timeout=30)
    logs = json.loads(r.read().decode())["logs"]
    print(f"Fetched {len(logs)} log entries")

    # Map task_id -> target IP
    task_ip: dict[str, str] = {}
    # Map task_id -> success bool
    task_result: dict[str, bool] = {}
    current_tid: str | None = None

    for e in logs:
        msg = e["msg"]

        m = re.search(r"Executing snmp_bulk_get for ([0-9a-f-]{36})", msg)
        if m:
            current_tid = m.group(1)

        m2 = re.search(r"snmp_bulk_get: target=(\S+)", msg)
        if m2 and current_tid:
            task_ip[current_tid] = m2.group(1)
            current_tid = None

        m3 = re.search(r"Handler returned for ([0-9a-f-]{36}).*success=(True|False)", msg)
        if m3:
            task_result[m3.group(1)] = m3.group(2) == "True"

    # Correlate by /24 subnet
    subnet_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})
    for tid, ip in task_ip.items():
        success = task_result.get(tid)
        if success is None:
            continue
        subnet = ".".join(ip.split(".")[:3])
        if success:
            subnet_stats[subnet]["ok"] += 1
        else:
            subnet_stats[subnet]["fail"] += 1

    # Also do /16 summary
    net16_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})
    for subnet, s in subnet_stats.items():
        net16 = ".".join(subnet.split(".")[:2]) + ".0.0/16"
        net16_stats[net16]["ok"] += s["ok"]
        net16_stats[net16]["fail"] += s["fail"]

    print(f"\nCorrelated {len(task_ip)} tasks with results\n")

    print("=== Per /24 subnet ===")
    print(f"{'Subnet':<20s} {'OK':>4s} {'Fail':>5s} {'Total':>6s} {'Success':>8s}")
    print("-" * 48)
    for subnet, s in sorted(subnet_stats.items(), key=lambda x: x[1]["ok"] + x[1]["fail"], reverse=True):
        total = s["ok"] + s["fail"]
        pct = 100 * s["ok"] / total if total else 0
        print(f"{subnet + '.0/24':<20s} {s['ok']:4d} {s['fail']:5d} {total:6d} {pct:7.0f}%")

    print(f"\n=== Per /16 network ===")
    print(f"{'Network':<20s} {'OK':>4s} {'Fail':>5s} {'Total':>6s} {'Success':>8s}")
    print("-" * 48)
    for net, s in sorted(net16_stats.items(), key=lambda x: x[1]["ok"] + x[1]["fail"], reverse=True):
        total = s["ok"] + s["fail"]
        pct = 100 * s["ok"] / total if total else 0
        print(f"{net:<20s} {s['ok']:4d} {s['fail']:5d} {total:6d} {pct:7.0f}%")


if __name__ == "__main__":
    main()
