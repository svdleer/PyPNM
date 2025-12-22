#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

try:
    import requests
except ImportError:
    print("The 'requests' library is not installed. Please install it before running this example.")
    sys.exit(2)

from pypnm.examples.common.common_cli import (
    DEFAULT_BASE_URL,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_TFTP_IPV6,
    EXIT_REQUEST_ERROR,
    EXIT_SUCCESS,
)

ENDPOINT_PATH: str = "/docs/pnm/ds/spectrumAnalyzer/getCapture/ofdm"
LOCAL_DEFAULT_HTTP_TIMEOUT_SEC: float = 180.0


def _join_url(base_url: str, endpoint_path: str) -> str:
    """
    Join Base URL And Endpoint Path Into A Single URL String.
    """
    base: str = base_url.rstrip("/")
    path: str = endpoint_path.lstrip("/")
    return f"{base}/{path}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PyPNM - Downstream OFDM Spectrum Analyzer (OFDM View)"
    )

    parser.add_argument(
        "--mac",
        "-m",
        required=True,
        help="MAC address of the cable modem",
    )
    parser.add_argument(
        "--inet",
        "-i",
        required=True,
        help="IP address of the cable modem",
    )
    parser.add_argument(
        "--tftp-ipv4",
        "-t4",
        required=True,
        help="IPv4 address of the TFTP server",
    )
    parser.add_argument(
        "--tftp-ipv6",
        "-t6",
        default=DEFAULT_TFTP_IPV6,
        help=f"IPv6 address of the TFTP server (default: {DEFAULT_TFTP_IPV6})",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for the PyPNM FastAPI service (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--community-write",
        "-cw",
        default=DEFAULT_SNMP_COMMUNITY,
        help=f"SNMP write community string (default: {DEFAULT_SNMP_COMMUNITY})",
    )
    parser.add_argument(
        "--num-averages",
        "-n",
        type=int,
        default=1,
        help="Number of averages for spectrum capture (default: 1)",
    )
    parser.add_argument(
        "--moving-average-points",
        "-p",
        type=int,
        default=10,
        help="Moving-average window points for spectrum_analysis (default: 10)",
    )
    parser.add_argument(
        "--retrieval-type",
        "-r",
        choices=["file", "snmp"],
        default="file",
        help="Spectrum retrieval mode: 'file' (PNM/TFTP) or 'snmp' (SNMP retrieval).",
    )
    parser.add_argument(
        "--http-timeout",
        "-T",
        type=float,
        default=LOCAL_DEFAULT_HTTP_TIMEOUT_SEC,
        help=f"HTTP request timeout in seconds (default: {LOCAL_DEFAULT_HTTP_TIMEOUT_SEC})",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    retrieval_type_value: int = 1 if args.retrieval_type == "file" else 2

    url: str = _join_url(args.base_url, ENDPOINT_PATH)

    payload: Dict[str, Any] = {
        "cable_modem": {
            "mac_address": args.mac,
            "ip_address": args.inet,
            "snmp": {
                "snmpV2C": {
                    "community": args.community_write,
                },
            },
            "pnm_parameters": {
                "tftp": {
                    "ipv4": args.tftp_ipv4,
                    "ipv6": args.tftp_ipv6,
                },
            },
        },
        "analysis": {
            "type": "basic",
            "output": {
                "type": "json",
            },
            "plot": {
                "ui": {
                    "theme": "dark",
                },
            },
            "spectrum_analysis": {
                "moving_average": {
                    "points": args.moving_average_points,
                },
            },
        },
        "capture_parameters": {
            "number_of_averages": args.num_averages,
            "spectrum_retrieval_type": retrieval_type_value,
        },
    }

    print()
    print(f"Sending POST to {url} with payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload, timeout=args.http_timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        print()
        print("Request failed:")
        print(str(exc))
        return EXIT_REQUEST_ERROR

    print()
    print("Response:")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)

    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
