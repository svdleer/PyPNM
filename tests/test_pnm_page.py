#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia
"""
PNM page integration test script.

Tests all configurable options on the PNM page against all 3 vendors to
catch regressions like UTSC vendor constraint bugs before deployment.

Usage:
    python tests/test_pnm_page.py                          # all vendors, all tests
    python tests/test_pnm_page.py --vendor casa            # one vendor
    python tests/test_pnm_page.py --test utsc              # one test group
    python tests/test_pnm_page.py --vendor arris --test utsc rxmer
    python tests/test_pnm_page.py --list                   # list available tests
    python tests/test_pnm_page.py --api http://localhost:8000  # custom API URL
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Lab configuration
# ---------------------------------------------------------------------------

VENDORS = {
    "arris": {
        "label": "CommScope E6000 (mnd-gt0002-ccap002)",
        "cmts_ip": "172.16.6.212",
        "community_read":  "Z1gg0@LL",
        "community_write": "Z1gg0Sp3c1@l",
        "test_modem_mac":  "90:32:4b:c8:19:0b",
        "test_modem_ip":   "10.206.234.92",
        "modem_community": "z1gg0m0n1t0r1ng",
    },
    "casa": {
        "label": "Casa Systems (mnd-gt0002-ccap101)",
        "cmts_ip": "172.16.6.201",
        "community_read":  "Z1gg0@LL",
        "community_write": "Z1gg0Sp3c1@l",
        "test_modem_mac":  "90:32:4b:c8:19:0b",
        "test_modem_ip":   "10.206.234.92",
        "modem_community": "z1gg0m0n1t0r1ng",
    },
    "cisco": {
        "label": "Cisco cBR-8 (mnd-gt0002-ccap201)",
        "cmts_ip": "172.16.6.202",
        "community_read":  "Z1gg0@LL",
        "community_write": "Z1gg0Sp3c1@l",
        "test_modem_mac":  "90:32:4b:c8:19:0b",
        "test_modem_ip":   "10.206.234.92",
        "modem_community": "z1gg0m0n1t0r1ng",
    },
}

DEFAULT_API = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    vendor:  str
    test:    str
    case:    str
    passed:  bool
    note:    str = ""
    details: Dict = field(default_factory=dict)


RESULTS: List[TestResult] = []


def record(vendor: str, test: str, case: str, passed: bool, note: str = "", details: Dict = None):
    r = TestResult(vendor, test, case, passed, note, details or {})
    RESULTS.append(r)
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {test} / {case}: {note}")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api_post(base: str, path: str, payload: Dict, timeout: int = 30) -> Dict:
    url = f"{base}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"_http_error": e.code, "_body": body}
    except Exception as e:
        return {"_exception": str(e)}


def api_get(base: str, path: str, timeout: int = 15) -> Dict:
    url = f"{base}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"_http_error": e.code, "_body": body}
    except Exception as e:
        return {"_exception": str(e)}


def ok(r: Dict) -> bool:
    """True if the response looks successful."""
    if "_exception" in r or "_http_error" in r:
        return False
    # Accept both {success:true} and {status:"ok"} shapes
    return r.get("success") is True or r.get("status") in ("ok", "success", 0)


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_utsc(api: str, vendor: str, cfg: Dict):
    """
    UTSC: test all window/output_format/num_bins combinations allowed per vendor.
    Vendor constraints enforced by the service layer — we verify clamp_warnings
    are present when an unsupported value is requested, and absent when valid.
    """
    print(f"\n  --- UTSC ---")

    cmts_ip  = cfg["cmts_ip"]
    write_comm = cfg["community_write"]

    # Discover first available RF port
    disc = api_post(api, "/api/pypnm/upstream/utsc/discover-rf-ports", {
        "cmts_ip": cmts_ip,
        "community": write_comm,
        "mac_address": cfg["test_modem_mac"],
        "modem_ip": cfg["test_modem_ip"],
    })
    rf_ports = disc.get("rf_ports", [])
    if not rf_ports:
        record(vendor, "utsc", "discover-rf-ports", False, f"no RF ports returned: {disc}")
        return
    rf_port = rf_ports[0].get("ifindex") or rf_ports[0].get("rf_port_ifindex")
    record(vendor, "utsc", "discover-rf-ports", bool(rf_port), f"port={rf_port}")
    if not rf_port:
        return

    base_params = {
        "cmts_ip": cmts_ip,
        "community": write_comm,
        "rf_port_ifindex": rf_port,
        "trigger_mode": 2,          # freeRunning
        "center_freq_hz": 37000000,
        "span_hz": 60000000,
        "num_bins": 800,
        "output_format": 2,         # fftPower — valid on all 3
        "window_function": 2,       # rectangular — valid on all 3
        "repeat_period_ms": 200,
        "freerun_duration_ms": 120000,
        "runtime": 20,
    }

    # --- Window function ---
    # All vendors accept 2 (rectangular)
    for wf, expect_clamp in [(2, False), (3, False), (6, vendor == "arris" or vendor == "cisco")]:
        p = {**base_params, "window_function": wf}
        r = api_post(api, f"/api/pypnm/upstream/utsc/configure/{cfg['test_modem_mac']}", p)
        clamped = bool(r.get("clamp_warnings"))
        passed = (clamped == expect_clamp) and ok(r)
        record(vendor, "utsc", f"window={wf}", passed,
               f"clamp_warnings={r.get('clamp_warnings', [])}" if not passed else f"ok clamp={clamped}")

    # --- Output format ---
    # Cisco: only 1,2,4 valid; others: 1-5 valid  (6 Casa only)
    valid_formats = {
        "arris": {1, 2, 3, 4, 5},
        "casa":  {1, 2, 3, 4, 5, 6},
        "cisco": {1, 2, 4},
    }
    for fmt in [1, 2, 4, 5, 6]:
        expect_clamp = fmt not in valid_formats.get(vendor, {1, 2})
        p = {**base_params, "output_format": fmt}
        r = api_post(api, f"/api/pypnm/upstream/utsc/configure/{cfg['test_modem_mac']}", p)
        clamped = bool(r.get("clamp_warnings"))
        passed = (clamped == expect_clamp) and ok(r)
        record(vendor, "utsc", f"output_format={fmt}", passed,
               f"clamp_warnings={r.get('clamp_warnings', [])}" if not passed else f"ok clamp={clamped}")

    # --- num_bins ---
    # Cisco: min 256 (128 silently ignored)
    valid_bins_cases = [(128, vendor == "cisco"), (256, False), (800, False), (4096, False)]
    for bins, expect_clamp in valid_bins_cases:
        p = {**base_params, "num_bins": bins}
        r = api_post(api, f"/api/pypnm/upstream/utsc/configure/{cfg['test_modem_mac']}", p)
        clamped = bool(r.get("clamp_warnings"))
        passed = (clamped == expect_clamp) and ok(r)
        record(vendor, "utsc", f"num_bins={bins}", passed,
               f"clamp_warnings={r.get('clamp_warnings', [])}" if not passed else f"ok clamp={clamped}")

    # --- Timing constraints ---
    timing_cases = [
        # repeat_ms, freerun_ms, expect_clamp, note
        (50,  120000, vendor == "casa",  "repeat=50ms (Casa min=100ms)"),
        (100, 120000, False,             "repeat=100ms ok all vendors"),
        (200, 60000,  vendor == "casa",  "freerun=60s (Casa min=120s)"),
        (200, 120000, False,             "freerun=120s ok all vendors"),
    ]
    for repeat_ms, freerun_ms, expect_clamp, note in timing_cases:
        p = {**base_params, "repeat_period_ms": repeat_ms, "freerun_duration_ms": freerun_ms}
        r = api_post(api, f"/api/pypnm/upstream/utsc/configure/{cfg['test_modem_mac']}", p)
        clamped = bool(r.get("clamp_warnings"))
        passed = (clamped == expect_clamp) and ok(r)
        record(vendor, "utsc", note, passed,
               f"clamp_warnings={r.get('clamp_warnings', [])}" if not passed else f"ok clamp={clamped}")


def test_rxmer(api: str, vendor: str, cfg: Dict):
    """US OFDMA RxMER: basic configure + status check."""
    print(f"\n  --- RxMER ---")

    mac  = cfg["test_modem_mac"]
    cmts = cfg["cmts_ip"]
    comm = cfg["community_write"]

    r = api_post(api, f"/api/pypnm/upstream/rxmer/configure/{mac}", {
        "cmts_ip": cmts,
        "community": comm,
        "mac_address": mac,
        "modem_ip": cfg["test_modem_ip"],
        "pre_eq": False,
        "num_averages": 1,
    })
    record(vendor, "rxmer", "configure", ok(r), str(r.get("error", r.get("message", ""))))

    time.sleep(2)

    r = api_post(api, f"/api/pypnm/upstream/rxmer/status/{mac}", {
        "cmts_ip": cmts,
        "community": comm,
        "mac_address": mac,
        "modem_ip": cfg["test_modem_ip"],
    })
    status = r.get("meas_status_name", r.get("status", ""))
    passed = ok(r) and status not in ("", None)
    record(vendor, "rxmer", "status", passed, f"meas_status={status}")


def test_pre_eq(api: str, vendor: str, cfg: Dict):
    """US OFDMA Pre-equalization capture."""
    print(f"\n  --- Pre-equalization ---")

    mac  = cfg["test_modem_mac"]
    cmts = cfg["cmts_ip"]
    comm = cfg["community_write"]

    r = api_post(api, f"/api/pypnm/upstream/preEqualization/getCapture/{mac}", {
        "cmts_ip": cmts,
        "community": comm,
        "mac_address": mac,
        "modem_ip": cfg["test_modem_ip"],
    })
    passed = ok(r) and "data" in r
    record(vendor, "pre_eq", "getCapture", passed, str(r.get("error", r.get("message", ""))))


def test_bulk_destination(api: str, vendor: str, cfg: Dict):
    """Bulk destination configure/list."""
    print(f"\n  --- Bulk Destination ---")

    cmts = cfg["cmts_ip"]
    comm = cfg["community_write"]

    r = api_post(api, "/api/pypnm/upstream/bulk-destination/list", {
        "cmts_ip": cmts,
        "community": comm,
    })
    passed = ok(r) and isinstance(r.get("destinations"), list)
    record(vendor, "bulk_dest", "list", passed, str(r.get("error", "")))


def test_api_health(api: str, vendor: str, cfg: Dict):
    """Quick API reachability check."""
    print(f"\n  --- API health ---")
    r = api_get(api, "/health")
    passed = r.get("status") in ("ok", "healthy") or r.get("success") is True
    record(vendor, "health", "GET /health", passed, str(r))


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

ALL_TESTS = {
    "health":   test_api_health,
    "utsc":     test_utsc,
    "rxmer":    test_rxmer,
    "pre_eq":   test_pre_eq,
    "bulk_dest": test_bulk_destination,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="PNM page integration tests")
    p.add_argument("--api", default=DEFAULT_API, metavar="URL",
                   help=f"PyPNM API base URL (default: {DEFAULT_API})")
    p.add_argument("--vendor", nargs="+", choices=list(VENDORS), metavar="VENDOR",
                   help="Vendors to test (default: all)")
    p.add_argument("--test", nargs="+", choices=list(ALL_TESTS), metavar="TEST",
                   help="Test groups to run (default: all)")
    p.add_argument("--list", action="store_true",
                   help="List available vendors and test groups")
    p.add_argument("--fail-fast", action="store_true",
                   help="Stop after first failure")
    return p.parse_args()


def main():
    args = parse_args()

    if args.list:
        print("Vendors:")
        for k, v in VENDORS.items():
            print(f"  {k:10s}  {v['label']}")
        print("\nTest groups:")
        for k in ALL_TESTS:
            print(f"  {k}")
        return 0

    vendors_to_run = args.vendor or list(VENDORS)
    tests_to_run   = args.test   or list(ALL_TESTS)

    print(f"API:     {args.api}")
    print(f"Vendors: {', '.join(vendors_to_run)}")
    print(f"Tests:   {', '.join(tests_to_run)}")
    print("=" * 60)

    for vendor in vendors_to_run:
        cfg = VENDORS[vendor]
        print(f"\n{'='*60}")
        print(f"VENDOR: {cfg['label']}")
        print(f"{'='*60}")

        for test_name in tests_to_run:
            fn = ALL_TESTS[test_name]
            try:
                fn(args.api, vendor, cfg)
            except Exception as e:
                record(vendor, test_name, "EXCEPTION", False, str(e))

            if args.fail_fast and any(not r.passed for r in RESULTS):
                print("\n[fail-fast] stopping after first failure.")
                break

        if args.fail_fast and any(not r.passed for r in RESULTS):
            break

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = [r for r in RESULTS if r.passed]
    failed = [r for r in RESULTS if not r.passed]
    print(f"  PASS: {len(passed)}")
    print(f"  FAIL: {len(failed)}")
    if failed:
        print("\nFailed tests:")
        for r in failed:
            print(f"  [{r.vendor}] {r.test} / {r.case}: {r.note}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
