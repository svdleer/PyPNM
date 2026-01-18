#!/bin/bash
# Test if UTSC OIDs exist on CMTS
# Run this on the server: ssh access-engineering.nl -p 65001

CMTS_IP="172.16.6.212"
COMMUNITY="Z1gg0@LL"
RF_PORT=1
CFG_IDX=1

echo "=== Testing UTSC OID Existence on CMTS ==="
echo "CMTS: $CMTS_IP"
echo

# UTSC Config Base OID
UTSC_CFG_BASE="1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
IDX=".$RF_PORT.$CFG_IDX"

echo "1. Testing UTSC Row Status (should exist):"
snmpget -v2c -c $COMMUNITY -t 2 $CMTS_IP ${UTSC_CFG_BASE}.24${IDX}

echo
echo "2. Testing UTSC Trigger Mode:"
snmpget -v2c -c $COMMUNITY -t 2 $CMTS_IP ${UTSC_CFG_BASE}.3${IDX}

echo
echo "3. Testing UTSC Center Frequency:"
snmpget -v2c -c $COMMUNITY -t 2 $CMTS_IP ${UTSC_CFG_BASE}.8${IDX}

echo
echo "4. Trying to walk the entire UTSC Config table:"
snmpwalk -v2c -c $COMMUNITY -t 2 -Cc $CMTS_IP $UTSC_CFG_BASE | head -20

echo
echo "=== End of OID Test ==="
