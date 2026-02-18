#!/usr/bin/env python3
"""
Test UTSC cfgIndex: .0 vs .1

Tests SNMP SET on UTSC OIDs with cfgIndex=0 vs cfgIndex=1
to determine which one the E6000 supports.

Usage: python test_utsc_cfgindex.py
"""

import requests
import json
import sys

PYPNM_API = "http://localhost:8000"
CMTS_IP = "172.16.6.212"
COMMUNITY = "Z1gg0Sp3c1@l"
RF_PORT = 1078534144  # MND-GT02-1 us-conn 0

# UTSC OID base: docsPnmCmtsUtscCfgTable
OID_BASE = "1.3.6.1.4.1.4491.2.1.27.1.3.1.1"

# Column 3 = trigger mode (integer, safe to test with GET first)
# Column 8 = center freq
# Column 13 = filename

def snmp_get(oid):
    """SNMP GET via PyPNM API agent."""
    resp = requests.post(f"{PYPNM_API}/snmp/get", json={
        "target": CMTS_IP,
        "community": COMMUNITY,
        "oids": [oid]
    }, timeout=30)
    return resp.json()

def snmp_set(oid, value, value_type='i'):
    """SNMP SET via PyPNM API agent."""
    resp = requests.post(f"{PYPNM_API}/snmp/set", json={
        "target": CMTS_IP,
        "community": COMMUNITY,
        "oid": oid,
        "value": value,
        "value_type": value_type
    }, timeout=30)
    return resp.json()

def snmp_walk(oid):
    """SNMP WALK via PyPNM API agent."""
    resp = requests.post(f"{PYPNM_API}/snmp/walk", json={
        "target": CMTS_IP,
        "community": COMMUNITY,
        "oid": oid
    }, timeout=30)
    return resp.json()


def test_walk_utsc_table():
    """Walk the UTSC config table to see what indexes exist."""
    print("=" * 60)
    print("Step 1: Walk UTSC Config Table to find valid indexes")
    print(f"  OID: {OID_BASE}")
    print("=" * 60)
    
    result = snmp_walk(OID_BASE)
    if result.get('success') and result.get('results'):
        for entry in result['results'][:20]:
            oid = entry.get('oid', '')
            value = entry.get('value', '')
            print(f"  {oid} = {value}")
        return True
    else:
        print(f"  Walk failed: {result.get('error', 'unknown')}")
        # Also try walking the parent
        print(f"\n  Trying parent OID walk: 1.3.6.1.4.1.4491.2.1.27.1.3")
        result2 = snmp_walk("1.3.6.1.4.1.4491.2.1.27.1.3")
        if result2.get('success') and result2.get('results'):
            for entry in result2['results'][:30]:
                oid = entry.get('oid', '')
                value = entry.get('value', '')
                print(f"  {oid} = {value}")
        else:
            print(f"  Parent walk also failed: {result2.get('error', 'unknown')}")
        return False


def test_get_cfgindex(cfg_index):
    """Test GET on UTSC trigger mode with given cfgIndex."""
    oid = f"{OID_BASE}.3.{RF_PORT}.{cfg_index}"
    print(f"\n  GET {oid}")
    result = snmp_get(oid)
    if result.get('success') and result.get('results'):
        value = result['results'][0].get('value', 'N/A')
        print(f"    -> OK: value = {value}")
        return True
    else:
        error = result.get('error', 'unknown')
        print(f"    -> FAIL: {error}")
        return False


def test_set_cfgindex(cfg_index):
    """Test SET on UTSC trigger mode with given cfgIndex."""
    # Set trigger mode to freeRunning (2)
    oid = f"{OID_BASE}.3.{RF_PORT}.{cfg_index}"
    print(f"\n  SET {oid} = 2 (freeRunning)")
    result = snmp_set(oid, 2, 'i')
    if result.get('success'):
        print(f"    -> OK: SET succeeded!")
        return True
    else:
        error = result.get('error', 'unknown')
        print(f"    -> FAIL: {error}")
        return False


def main():
    print("UTSC cfgIndex Test")
    print(f"CMTS: {CMTS_IP}")
    print(f"RF Port: {RF_PORT}")
    print(f"Community: {COMMUNITY}")
    print()
    
    # Step 1: Walk the table
    test_walk_utsc_table()
    
    # Step 2: Test GET with cfgIndex=0 and cfgIndex=1
    print("\n" + "=" * 60)
    print("Step 2: Test GET with cfgIndex=0 vs cfgIndex=1")
    print("=" * 60)
    
    get_0 = test_get_cfgindex(0)
    get_1 = test_get_cfgindex(1)
    
    # Step 3: Test SET with cfgIndex=0 and cfgIndex=1
    print("\n" + "=" * 60)
    print("Step 3: Test SET with cfgIndex=0 vs cfgIndex=1")
    print("=" * 60)
    
    set_0 = test_set_cfgindex(0)
    set_1 = test_set_cfgindex(1)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  GET  cfgIndex=0: {'✅ OK' if get_0 else '❌ FAIL'}")
    print(f"  GET  cfgIndex=1: {'✅ OK' if get_1 else '❌ FAIL'}")
    print(f"  SET  cfgIndex=0: {'✅ OK' if set_0 else '❌ FAIL'}")
    print(f"  SET  cfgIndex=1: {'✅ OK' if set_1 else '❌ FAIL'}")
    
    if set_0 and not set_1:
        print("\n  >>> cfgIndex=0 is correct! Change .1 to .0 in UTSCService <<<")
    elif set_1 and not set_0:
        print("\n  >>> cfgIndex=1 is correct (current code is fine)")
    elif set_0 and set_1:
        print("\n  >>> Both work - but .0 is the standard cfgIndex")
    else:
        print("\n  >>> Neither worked - different issue!")


if __name__ == '__main__':
    main()
