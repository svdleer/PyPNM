#!/usr/bin/env python3
"""Run DOCSIS downstream spectrum analyzer capture via PyPNM API with agent checks.

This script targets deployments where PyPNM uses agent SNMP transport.
It can run a single capture or an A/B timeout sweep against one modem.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib import error, request


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _http_get_json(url: str, timeout: float) -> dict[str, Any]:
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="ignore")
    return json.loads(payload)


def _http_post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any], float]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        code = int(resp.getcode())
    elapsed = time.monotonic() - t0
    return code, json.loads(body), elapsed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run modem spectrum analyzer test through PyPNM + agents")
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="PyPNM API base URL")
    p.add_argument("--mac", required=True, help="Cable modem MAC, e.g. 48:d3:43:a9:59:db")
    p.add_argument("--ip", required=True, help="Cable modem IPv4/IPv6 address")
    p.add_argument("--community", required=True, help="SNMP v2c community for modem")
    p.add_argument("--tftp-ipv4", required=True, help="TFTP IPv4 endpoint")
    p.add_argument("--tftp-ipv6", default="::1", help="TFTP IPv6 endpoint")
    p.add_argument(
        "--inactivity-timeouts",
        default="60",
        help="Comma-separated inactivity timeout(s), e.g. 60 or 60,300",
    )
    p.add_argument("--first-segment-center-freq", type=int, default=108000000)
    p.add_argument("--last-segment-center-freq", type=int, default=993000000)
    p.add_argument("--segment-freq-span", type=int, default=1000000)
    p.add_argument("--num-bins-per-segment", type=int, default=256)
    p.add_argument("--moving-average-points", type=int, default=10)
    p.add_argument(
        "--spectrum-retrieval-type",
        type=int,
        default=1,
        choices=[1, 2],
        help="1=file retrieval, 2=SNMP retrieval",
    )
    p.add_argument("--http-timeout", type=float, default=420.0, help="HTTP timeout for each capture request")
    p.add_argument(
        "--require-agent",
        action="store_true",
        help="Fail immediately if /api/agents has zero connected agents",
    )
    p.add_argument("--print-raw", action="store_true", help="Print full JSON response")
    return p


def _build_payload(args: argparse.Namespace, inactivity_timeout: int) -> dict[str, Any]:
    return {
        "cable_modem": {
            "mac_address": args.mac,
            "ip_address": args.ip,
            "snmp": {"snmp_v2c": {"community": args.community}},
            "pnm_parameters": {
                "tftp": {"ipv4": args.tftp_ipv4, "ipv6": args.tftp_ipv6},
            },
        },
        "analysis": {
            "type": "basic",
            "output": {"type": "json"},
            "plot": {"ui": {"theme": "light"}},
            "spectrum_analysis": {"moving_average": {"points": args.moving_average_points}},
        },
        "capture_parameters": {
            "inactivity_timeout": inactivity_timeout,
            "first_segment_center_freq": args.first_segment_center_freq,
            "last_segment_center_freq": args.last_segment_center_freq,
            "segment_freq_span": args.segment_freq_span,
            "num_bins_per_segment": args.num_bins_per_segment,
            "spectrum_retrieval_type": args.spectrum_retrieval_type,
        },
    }


def _parse_timeouts(raw: str) -> list[int]:
    out: list[int] = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        val = int(token)
        if val <= 0:
            raise ValueError("timeouts must be positive")
        out.append(val)
    if not out:
        raise ValueError("at least one inactivity timeout is required")
    return out


def main() -> int:
    args = _build_parser().parse_args()

    try:
        timeouts = _parse_timeouts(args.inactivity_timeouts)
    except Exception as exc:
        print(f"Invalid --inactivity-timeouts: {exc}", file=sys.stderr)
        return 2

    agents_url = _join_url(args.base_url, "/api/agents")
    capture_url = _join_url(args.base_url, "/docs/pnm/ds/spectrumAnalyzer/getCapture")

    try:
        agents_info = _http_get_json(agents_url, timeout=15.0)
    except Exception as exc:
        print(f"Agent API check failed: {exc}", file=sys.stderr)
        if args.require_agent:
            return 3
        agents_info = {"count": "unknown", "agents": []}

    count = agents_info.get("count", "unknown")
    print(f"Agent status: count={count}")

    if args.require_agent and isinstance(count, int) and count <= 0:
        print("No connected agents found and --require-agent was set", file=sys.stderr)
        return 4

    overall_ok = True

    for inactivity_timeout in timeouts:
        payload = _build_payload(args, inactivity_timeout)
        print(f"\nRunning capture with inactivity_timeout={inactivity_timeout}s ...")
        try:
            http_code, rsp, elapsed = _http_post_json(capture_url, payload, timeout=args.http_timeout)
        except error.HTTPError as exc:
            txt = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
            print(f"HTTP error: code={exc.code} body={txt}", file=sys.stderr)
            overall_ok = False
            continue
        except Exception as exc:
            print(f"Request failed: {exc}", file=sys.stderr)
            overall_ok = False
            continue

        status = rsp.get("status")
        message = rsp.get("message", "")
        print(f"Result: http={http_code} status={status} elapsed={elapsed:.2f}s message={message}")

        if args.print_raw:
            print(json.dumps(rsp, indent=2))

        if status != 0:
            overall_ok = False

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
