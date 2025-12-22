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
    print("The 'requests' library is not installed. Please install it before running these examples.")
    sys.exit(2)

from pypnm.examples.common.common_cli import (
    DEFAULT_BASE_URL,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_TFTP_IPV6,
    EXIT_SUCCESS,
    EXIT_REQUEST_ERROR,
    _join_url,
)


def _parse_args() -> argparse.Namespace:
    """
    Parse Command Line Arguments For Downstream Spectrum Analyzer Segment Sweep Example.
    """
    parser = argparse.ArgumentParser(
        description="PNM - Downstream Spectrum Analyzer Segment Sweep (FastAPI Example)"
    )

    parser.add_argument(
        "--mac",
        "-m",
        required=True,
        help="Cable modem MAC address (aa:bb:cc:dd:ee:ff).",
    )
    parser.add_argument(
        "--inet",
        "-i",
        required=True,
        help="Cable modem IPv4 address (192.168.0.1).",
    )
    parser.add_argument(
        "--tftp-ipv4",
        "-t4",
        required=True,
        help="TFTP server IPv4 address for PNM file delivery.",
    )
    parser.add_argument(
        "--tftp-ipv6",
        "-t6",
        default=DEFAULT_TFTP_IPV6,
        help=f"TFTP server IPv6 address for PNM file delivery (default: {DEFAULT_TFTP_IPV6}).",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        default=DEFAULT_BASE_URL,
        help=f"PyPNM FastAPI base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--community",
        "-c",
        default=DEFAULT_SNMP_COMMUNITY,
        help=f"SNMP v2c community string (default: {DEFAULT_SNMP_COMMUNITY}).",
    )

    # Analysis controls
    parser.add_argument(
        "--ma-points",
        type=int,
        default=10,
        help="Moving average points for spectrum post-processing (default: 10).",
    )

    # Capture / sweep controls
    parser.add_argument(
        "--inactivity-timeout",
        type=int,
        default=60,
        help="Inactivity timeout in seconds for the spectrum measurement (default: 60).",
    )
    parser.add_argument(
        "--first-segment-center-freq",
        type=int,
        default=300_000_000,
        help="First segment center frequency in Hz (default: 300000000).",
    )
    parser.add_argument(
        "--last-segment-center-freq",
        type=int,
        default=990_000_000,
        help="Last segment center frequency in Hz (default: 990000000).",
    )
    parser.add_argument(
        "--segment-freq-span",
        type=int,
        default=1_000_000,
        help="Frequency span per segment in Hz (default: 1000000).",
    )
    parser.add_argument(
        "--num-bins-per-segment",
        type=int,
        default=256,
        help="Number of FFT bins per segment (default: 256).",
    )
    parser.add_argument(
        "--noise-bw",
        type=int,
        default=150,
        help="Noise bandwidth in kHz (device-specific, default: 150).",
    )
    parser.add_argument(
        "--window-function",
        type=int,
        default=1,
        help="Window function selector (device-specific, default: 1).",
    )
    parser.add_argument(
        "--num-averages",
        type=int,
        default=1,
        help="Number of averages for each segment (default: 1).",
    )

    # Retrieval type: file (TFTP PNM) or snmp (direct retrieval)
    parser.add_argument(
        "--retrieval-type",
        choices=["file", "snmp"],
        default="file",
        help="Spectrum retrieval type: 'file' for PNM file via TFTP, 'snmp' for direct SNMP (default: file).",
    )

    # HTTP timeout for the FastAPI request
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=180.0,
        help="HTTP timeout in seconds for the FastAPI request (default: 180).",
    )

    return parser.parse_args()


def _map_retrieval_type(label: str) -> int:
    """
    Map Human Friendly Retrieval Type To API Enumeration.

    'file' -> 1 (PNM file via TFTP)
    'snmp' -> 2 (Direct SNMP retrieval)
    """
    if label == "file":
        return 1
    if label == "snmp":
        return 2
    raise ValueError(f"Unsupported retrieval type: {label!r}")


def main() -> int:
    """
    Build Payload And Send POST Request To /docs/pnm/ds/spectrumAnalyzer/getCapture.
    """
    args = _parse_args()

    retrieval_type_value: int = _map_retrieval_type(args.retrieval_type)

    url: str = _join_url(args.base_url, "/docs/pnm/ds/spectrumAnalyzer/getCapture")

    # Build payload to match the FastAPI endpoint schema
    payload: Dict[str, Any] = {
        "cable_modem": {
            "mac_address": args.mac,
            "ip_address": args.inet,
            "pnm_parameters": {
                "tftp": {
                    "ipv4": args.tftp_ipv4,
                    "ipv6": args.tftp_ipv6,
                },
            },
            "snmp": {
                "snmpV2C": {
                    "community": args.community,
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
                    "points": args.ma_points,
                },
            },
        },
        "capture_parameters": {
            "inactivity_timeout": args.inactivity_timeout,
            "first_segment_center_freq": args.first_segment_center_freq,
            "last_segment_center_freq": args.last_segment_center_freq,
            "segment_freq_span": args.segment_freq_span,
            "num_bins_per_segment": args.num_bins_per_segment,
            "noise_bw": args.noise_bw,
            "window_function": args.window_function,
            "num_averages": args.num_averages,
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
