# OFDM MER Margin

The purpose of this item is to provide an estimate of the MER margin available on the downstream data channel with respect to a modulation profile. The profile may be a profile that the modem has already been assigned or a candidate profile. This is similar to the MER Margin reported in the OPT-RSP Message \[MULPIv3.1].

The CM calculates the Required Average MER for the profile based on the bit loading for the profile and the Required MER per Modulation Order provided in the CmDsOfdmRequiredQamMer table. For profiles with mixed modulation orders, this value is computed as an arithmetic mean of the required MER values for each non-excluded subcarrier in the Modulated Spectrum. The CM then measures the RxMER per subcarrier and calculates the Average MER for the Active Subcarriers used in the Profile and stores the value as MeasuredAvgMer. The Operator may also compute the value for Required Average MER for the profile and set that value for the test.

The CM also counts the number of MER per Subcarrier values that are below the threshold determined by the CmDsOfdmRequiredQamMer and the ThrshldOffset. The CM reports that value as NumSubcarriersBelowThrshld.

This table will have a row for each ifIndex for the modem.

## Table of Contents

* [Get Measurement](#get-measurement)

---

## Get Measurement

### Endpoint

**POST** `/docs/pnm/ds/ofdm/merMargin/getMeasurement`

Initiates a MER margin measurement on a DOCSIS 3.1 downstream OFDM profile.

### Request Body (JSON)

```json
{
  "cable_modem": {
  "mac_address": "aa:bb:cc:dd:ee:ff", 
  "ip_address": "192.168.0.100",
  "snmp": {
    "snmpV2C": {
      "community": "private"
    },
    "snmpV3": {
      "username": "string",
      "securityLevel": "noAuthNoPriv",
      "authProtocol": "MD5",
      "authPassword": "string",
      "privProtocol": "DES",
      "privPassword": "string"
    }
  }
}
