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

DEFAULT_GUI = "http://localhost:5050"

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
        "test_modem_mac":  "e4:57:40:0b:cf:70",
        "test_modem_ip":   "10.206.228.4",
        "modem_community": "z1gg0m0n1t0r1ng",
    },
    "cisco": {
        "label": "Cisco cBR-8 (mnd-gt0002-ccap201)",
        "cmts_ip": "172.16.6.202",
        "community_read":  "Z1gg0@LL",
        "community_write": "Z1gg0Sp3c1@l",
        "test_modem_mac":  "d4:6a:6a:fd:00:b3",
        "test_modem_ip":   "10.254.70.11",
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


# Set to True via --offline to skip SNMP-dependent assertions (CI without lab access)
OFFLINE: bool = False


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

def test_utsc(api: str, vendor: str, cfg: Dict, gui: str = ""):
    """
    UTSC: test all window/output_format/num_bins combinations allowed per vendor.
    Vendor constraints enforced by the service layer — we verify clamp_warnings
    are present when an unsupported value is requested, and absent when valid.
    """
    print(f"\n  --- UTSC ---")

    cmts_ip  = cfg["cmts_ip"]
    write_comm = cfg["community_write"]

    # Discover first available RF port
    # GUI backend route: /api/pypnm/upstream/interfaces/<mac>
    gui_base = gui or api
    disc = api_post(gui_base, f"/api/pypnm/upstream/interfaces/{cfg['test_modem_mac']}", {
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


def test_rxmer(api: str, vendor: str, cfg: Dict, gui: str = ""):
    """US OFDMA RxMER: basic start + status check via GUI backend."""
    print(f"\n  --- RxMER ---")

    mac      = cfg["test_modem_mac"]
    cmts     = cfg["cmts_ip"]
    comm     = cfg["community_write"]
    gui_base = gui or api

    r = api_post(gui_base, f"/api/pypnm/upstream/rxmer/start/{mac}", {
        "cmts_ip": cmts,
        "community": comm,
        "ofdma_ifindex": cfg.get("ofdma_ifindex", 0),
    })
    record(vendor, "rxmer", "start", ok(r), str(r.get("error", r.get("message", ""))))

    time.sleep(3)

    r = api_post(gui_base, f"/api/pypnm/upstream/rxmer/status/{mac}", {
        "cmts_ip": cmts,
        "community": comm,
    })
    status = r.get("meas_status_name", r.get("status", r.get("meas_status", "")))
    passed = ok(r) and status not in ("", None)
    record(vendor, "rxmer", "status", passed, f"meas_status={status}")


def test_pre_eq(api: str, vendor: str, cfg: Dict, gui: str = ""):
    """US pre-equalization capture via GUI backend (/modem/<mac>/pre-eq)."""
    print(f"\n  --- Pre-equalization ---")

    mac      = cfg["test_modem_mac"]
    cmts     = cfg["cmts_ip"]
    comm     = cfg["community_read"]
    gui_base = gui or api

    r = api_post(gui_base, f"/api/pypnm/modem/{mac}/pre-eq", {
        "cmts_ip": cmts,
        "community": comm,
        "modem_ip": cfg["test_modem_ip"],
    })
    passed = ok(r) and ("data" in r or "plot" in r or "pre_eq" in r)
    record(vendor, "pre_eq", "pre-eq", passed, str(r.get("error", r.get("message", ""))))


def test_bulk_destination(api: str, vendor: str, cfg: Dict, gui: str = ""):
    """Bulk destination: configure via PyPNM API directly."""
    print(f"\n  --- Bulk Destination ---")

    cmts = cfg["cmts_ip"]
    comm = cfg["community_write"]

    # PyPNM API direct endpoint
    r = api_post(api, "/pnm/us/bulk-destination", {
        "cmts_ip": cmts,
        "community": comm,
        "write_community": comm,
        "dest_ip": "127.0.0.1",  # dummy — just test the endpoint exists
        "dest_path": "./",
        "index": 1,
    })
    not_missing = r.get("_http_error") not in (404, 405) and "_exception" not in r
    record(vendor, "bulk_dest", "bulk-destination endpoint exists", not_missing,
           f"http={r.get('_http_error')} success={r.get('success')}")


def test_api_health(api: str, vendor: str, cfg: Dict):
    """Quick API reachability check."""
    print(f"\n  --- API health ---")
    r = api_get(api, "/health")
    passed = r.get("status") in ("ok", "healthy") or r.get("success") is True
    record(vendor, "health", "GET /health", passed, str(r))


def test_modem_enrichment(api: str, vendor: str, cfg: Dict):
    """
    Regression: GET /cmts/modems must return enriched fields.
    Catches: wrong HTTP method (405), fields dropped in modem map,
    Redis intercepting enrichment poll.
    """
    print(f"\n  --- modem enrichment ---")

    # 1. Base call — must succeed (no 405)
    path = (f"/cmts/modems?cmts_ip={cfg['cmts_ip']}"
            f"&community={cfg['community_read']}&limit=3&enrich=false")
    r = api_get(api, path)
    passed = r.get("success") is True and "_http_error" not in r
    record(vendor, "enrichment", "GET /cmts/modems (base)", passed,
           f"http_error={r.get('_http_error', 'none')}")

    # 2. Enriched call — wait up to 90s for enrichment to complete
    path_enrich = (f"/cmts/modems?cmts_ip={cfg['cmts_ip']}"
                   f"&community={cfg['community_read']}&limit=5"
                   f"&enrich=true&modem_community={cfg['modem_community']}")
    enriched = False
    for attempt in range(6):
        r2 = api_get(api, path_enrich, timeout=30)
        if r2.get("enriched"):
            enriched = True
            break
        if attempt < 5:
            time.sleep(15)

    record(vendor, "enrichment", "GET /cmts/modems enriched=True", enriched,
           f"enriched={r2.get('enriched')} enriching={r2.get('enriching')}")

    if enriched:
        modems = r2.get("modems", [])
        m = modems[0] if modems else {}
        has_vendor   = bool(m.get("vendor"))
        has_ofdma    = "ofdma_enabled" in m
        has_docsis   = bool(m.get("docsis_version"))
        record(vendor, "enrichment", "modem.vendor present",   has_vendor,   str(m.get("vendor")))
        record(vendor, "enrichment", "modem.ofdma_enabled key exists", has_ofdma, str(m.get("ofdma_enabled")))
        record(vendor, "enrichment", "modem.docsis_version present", has_docsis, str(m.get("docsis_version")))


def test_rf_port_discovery(api: str, vendor: str, cfg: Dict):
    """
    Regression: /spectrumAnalyzer/discoverRfPort must exist (not 404/405).
    In offline mode: only checks the endpoint is registered (no SNMP to CMTS).
    Online mode: also validates the returned ifindex is a real value (> 1000).
    Catches: endpoint returning 404, duplicate registered at module level.
    """
    print(f"\n  --- RF port discovery ---")
    r = api_post(api, "/pnm/us/spectrumAnalyzer/discoverRfPort", {
        "cmts_ip": cfg["cmts_ip"],
        "community": cfg["community_read"],
        "cm_mac_address": cfg["test_modem_mac"],
    }, timeout=30)

    http_err = r.get("_http_error")
    # Offline: endpoint must exist — any response except 404/405 is a pass
    not_missing = http_err not in (404, 405) and "_exception" not in r
    record(vendor, "rf_port", "discoverRfPort endpoint exists (not 404/405)", not_missing,
           f"http={http_err}")

    if not OFFLINE:
        passed  = r.get("success") is True and bool(r.get("rf_port_ifindex")) and not http_err
        ifindex = r.get("rf_port_ifindex") or 0
        sane    = isinstance(ifindex, int) and ifindex > 1000
        record(vendor, "rf_port", "discoverRfPort success", passed,
               f"http={http_err} ifindex={ifindex}")
        record(vendor, "rf_port", "rf_port_ifindex > 1000 (sane)", sane,
               f"ifindex={ifindex}")


def test_ofdma_discovery(api: str, vendor: str, cfg: Dict):
    """
    Regression: /ofdma/rxmer/discover must exist and return a sane ofdma_ifindex.
    In offline mode: only checks the endpoint is registered (no SNMP to CMTS).
    Online mode: also validates ifindex > 100 (catches false OID match returning 3).
    Catches: false OID match on cm_index=1 matching base OID prefix.
    """
    print(f"\n  --- OFDMA ifindex discovery ---")
    r = api_post(api, "/pnm/us/ofdma/rxmer/discover", {
        "cmts": {
            "cmts_ip": cfg["cmts_ip"],
            "community": cfg["community_read"],
            "write_community": cfg["community_write"],
        },
        "cm_mac_address": cfg["test_modem_mac"],
    }, timeout=30)

    http_err = r.get("_http_error")
    not_missing = http_err not in (404, 405) and "_exception" not in r
    record(vendor, "ofdma_disc", "ofdma/rxmer/discover endpoint exists (not 404/405)", not_missing,
           f"http={http_err}")

    if not OFFLINE:
        passed  = r.get("success") is True and bool(r.get("ofdma_ifindex"))
        ifindex = r.get("ofdma_ifindex") or 0
        # Real OFDMA ifIndexes are always large (CommScope ~843M, Cisco ~488K, Casa similar)
        # A value <= 100 means OID parsing picked up a base-OID component, not the real ifindex
        sane    = isinstance(ifindex, int) and ifindex > 100
        record(vendor, "ofdma_disc", "ofdma/rxmer/discover success", passed,
               f"ifindex={ifindex} desc={r.get('ofdma_description')}")
        record(vendor, "ofdma_disc", "ofdma_ifindex > 100 (not OID component)", sane,
               f"ifindex={ifindex}")


def test_websocket_stream(api: str, vendor: str, cfg: Dict):
    """
    Regression: WebSocket /spectrumAnalyzer/stream must be reachable.
    Catches: __skip_autoregister__ on router silencing the WebSocket endpoint.
    Only runs once (vendor-independent), skips if websockets package unavailable.
    """
    print(f"\n  --- WebSocket stream ---")

    # Only test once — endpoint is not vendor-specific
    if vendor != list(VENDORS.keys())[0]:
        record(vendor, "ws_stream", "skipped (vendor-agnostic, tested once)", True, "n/a")
        return

    ws_url = api.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += "/pnm/us/spectrumAnalyzer/stream"

    try:
        import asyncio
        import importlib
        ws_mod = importlib.import_module("websockets")

        async def _check():
            async with ws_mod.connect(ws_url, open_timeout=5):
                return True

        connected = asyncio.run(_check())
        record(vendor, "ws_stream", f"WS connect {ws_url}", connected, "")
    except ImportError:
        record(vendor, "ws_stream", "websockets package missing — skipped", True,
               "pip install websockets to enable")
    except Exception as e:
        record(vendor, "ws_stream", f"WS connect {ws_url}", False, str(e))


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

ALL_TESTS = {
    "health":      test_api_health,
    "enrichment":  test_modem_enrichment,
    "rf_port":     test_rf_port_discovery,
    "ofdma_disc":  test_ofdma_discovery,
    "ws_stream":   test_websocket_stream,
    "utsc":        test_utsc,
    "rxmer":       test_rxmer,
    "pre_eq":      test_pre_eq,
    "bulk_dest":   test_bulk_destination,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="PNM page integration tests")
    p.add_argument("--api", default=DEFAULT_API, metavar="URL",
                   help=f"PyPNM API base URL (default: {DEFAULT_API})")
    p.add_argument("--gui", default=DEFAULT_GUI, metavar="URL",
                   help=f"PyPNMGui backend URL (default: {DEFAULT_GUI})")
    p.add_argument("--vendor", nargs="+", choices=list(VENDORS), metavar="VENDOR",
                   help="Vendors to test (default: all)")
    p.add_argument("--test", nargs="+", choices=list(ALL_TESTS), metavar="TEST",
                   help="Test groups to run (default: all)")
    p.add_argument("--list", action="store_true",
                   help="List available vendors and test groups")
    p.add_argument("--fail-fast", action="store_true",
                   help="Stop after first failure")
    p.add_argument("--offline", action="store_true",
                   help="Offline/CI mode: only verify endpoints exist, skip SNMP assertions")
    return p.parse_args()


def main():
    args = parse_args()

    global OFFLINE
    OFFLINE = args.offline
    if OFFLINE:
        print("[offline mode] SNMP assertions skipped — checking endpoint existence only")

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
                import inspect
                if "gui" in inspect.signature(fn).parameters:
                    fn(args.api, vendor, cfg, gui=args.gui)
                else:
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
