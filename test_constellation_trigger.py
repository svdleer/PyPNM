#!/usr/bin/env python3
import requests
import json

# Test constellation measurement
url = "http://localhost:8000/docs/pnm/ds/ofdm/constellationDisplay/getCapture"

payload = {
    "cable_modem": {
        "mac_address": "90:32:4b:c8:13:73",
        "ip_address": "10.206.234.3",
        "snmp": {
            "snmpV2C": {
                "community": "z1gg0m0n1t0r1ng"
            }
        },
        "pnm_parameters": {
            "tftp": {
                "ipv4": "172.22.147.18",
                "ipv6": "::1"
            }
        }
    },
    "capture_settings": {
        "modulation_order_offset": 0,
        "number_sample_symbol": 8192
    },
    "analysis": {
        "type": "basic",
        "output": {
            "type": "archive"
        },
        "plot": {
            "ui": {
                "theme": "dark"
            },
            "options": {
                "display_cross_hair": True
            }
        }
    }
}

print("Triggering constellation measurement...")
response = requests.post(url, json=payload, timeout=120)
print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")
