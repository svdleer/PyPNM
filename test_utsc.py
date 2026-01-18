#!/usr/bin/env python3
"""
Test UTSC (Upstream Triggered Spectrum Capture) Implementation
Requires: CMTS access, RF port ifIndex
"""

import requests
import json

# Test Configuration
PYPNM_API_URL = "http://localhost:8081"
CMTS_IP = "172.16.6.212"
CMTS_COMMUNITY = "Z1gg0Sp3c1@l"  # Write community for SNMP SET operations
RF_PORT_IFINDEX = 1074339840  # us-conn 0 (upstream connector with existing UTSC config)
MODEM_MAC = "00:00:00:00:00:00"  # OPTIONAL - for trigger mode 6
TFTP_IP = "172.16.6.101"  # Use TFTP from pypnm_system.json

def test_utsc_freerunning():
    """Test UTSC with FreeRunning trigger mode (no modem MAC needed)"""
    print("\n=== Testing UTSC - FreeRunning Mode ===")
    
    payload = {
        "cmts": {
            "cmts_ip": CMTS_IP,
            "rf_port_ifindex": RF_PORT_IFINDEX,
            "community": CMTS_COMMUNITY
        },
        "tftp": {
            "ipv4": TFTP_IP,
            "ipv6": None
        },
        "trigger": {},
        "capture_parameters": {
            "trigger_mode": 2,  # FreeRunning
            "center_freq_hz": 30000000,
            "span_hz": 80000000,
            "num_bins": 800,
            "filename": "utsc_test_freerun"
        },
        "analysis": {
            "output_type": "json"
        }
    }
    
    try:
        print(f"Sending request with payload: {json.dumps(payload, indent=2)}")
        response = requests.post(
            f"{PYPNM_API_URL}/docs/pnm/us/spectrumAnalyzer/getCapture",
            json=payload,
            timeout=90
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        return response.status_code == 200
    except requests.exceptions.Timeout as e:
        print(f"TIMEOUT: Request took longer than 90 seconds")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_utsc_cm_mac():
    """Test UTSC with CM MAC trigger mode"""
    print("\n=== Testing UTSC - CM MAC Trigger Mode ===")
    
    payload = {
        "cmts": {
            "cmts_ip": CMTS_IP,
            "rf_port_ifindex": RF_PORT_IFINDEX,
            "community": CMTS_COMMUNITY
        },
        "tftp": {
            "ipv4": TFTP_IP,
            "ipv6": None
        },
        "trigger": {
            "cm_mac": MODEM_MAC,
            "logical_ch_ifindex": RF_PORT_IFINDEX
        },
        "capture_parameters": {
            "trigger_mode": 6,  # CM MAC Address
            "center_freq_hz": 30000000,
            "span_hz": 80000000,
            "num_bins": 800,
            "filename": "utsc_test_cmmac"
        },
        "analysis": {
            "output_type": "json"
        }
    }
    
    try:
        print(f"Sending request with payload: {json.dumps(payload, indent=2)}")
        response = requests.post(
            f"{PYPNM_API_URL}/docs/pnm/us/spectrumAnalyzer/getCapture",
            json=payload,
            timeout=90
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        return response.status_code == 200
    except requests.exceptions.Timeout as e:
        print(f"TIMEOUT: Request took longer than 90 seconds")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


if __name__ == "__main__":
    print("UTSC Implementation Test")
    print("=" * 50)
    print(f"CMTS: {CMTS_IP}")
    print(f"RF Port ifIndex: {RF_PORT_IFINDEX}")
    print(f"PyPNM API: {PYPNM_API_URL}")
    
    # Test FreeRunning mode first (doesn't need modem MAC)
    success1 = test_utsc_freerunning()
    
    # Test CM MAC mode if modem MAC is configured
    if MODEM_MAC != "00:00:00:00:00:00":
        success2 = test_utsc_cm_mac()
    else:
        print("\nSkipping CM MAC test - no modem MAC configured")
        success2 = True
    
    print("\n" + "=" * 50)
    if success1 and success2:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
