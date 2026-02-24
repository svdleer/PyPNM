# Base UTSC / RxMER Capture Settings
## Source: test_utsc_cisco.py — confirmed working 24 February 2026

---

## UTSC Capture Parameters

| Parameter | Value | Notes |
|---|---|---|
| `TRIGGER_MODE` | `2` | freeRunning |
| `CENTER_FREQ` | `16,400,000 Hz` | 16.4 MHz |
| `SPAN` | `6,400,000 Hz` | 6.4 MHz |
| `NUM_BINS` | `1024` | |
| `AVG_NUMBER` | `245` | |
| `OUTPUT_FORMAT` | `1` | fftPower — E6000 uses `5` (fftAmplitude) |
| `WINDOW` | `3` | Hann — E6000 uses `4` (Blackman-Harris) |
| `REPEAT_PERIOD` | `25,000 µs` | 25ms |
| `FREE_RUN_DURATION` | `5,000 ms` | 5s |
| `TRIGGER_COUNT` | `1` | |
| `FILENAME` | `utsc_spectrum` | |
| `CFG_INDEX` | `1` | |
| `BDT_ROW` | `1` | Bulk Data Transfer row index |

---

## Lab CMTS ifIndex

| CMTS | IP | ifIndex | Interface | Notes |
|---|---|---|---|---|
| Cisco cBR-8 | 172.16.6.202 | `488046` | Cable1/0/0-upstream6 (OFDMA) | confirmed working |
| Casa C100G | 172.16.6.201 | `4000048` | Upstream Physical Interface 0/6.0 | cfg_index=3, TriggerMode=2 |

---

## TFTP Settings

| Vendor/Env | TFTP IP | Notes |
|---|---|---|
| Cisco (lab) | `172.22.147.18` | Lab-specific, set in `lab-config.json` as `tftp_ip_lab_cisco` |
| Default | `172.16.6.101` | From `pypnm_system.json` PnmBulkDataTransfer.tftp.ip_v4 |

---

## Vendor Provisioning Flow

### Cisco cBR-8
```
1. BDT:  RowStatus=6 (destroy) → sleep 2s → RowStatus=4 (createAndGo) → sleep 1s
         SET DestHostIpAddrType, DestHostIpAddress, DestBaseUri
         DO NOT SET Protocol — Cisco defaults it from createAndGo (genError if SET)

2. UTSC: RowStatus=6 (destroy) → sleep 2s → RowStatus=4 (createAndGo) → sleep 1s
         SET LogicalChIfIndex, TriggerMode, NumBins, CenterFreq, Span,
             OutputFormat, Window, FreeRunDuration, RepeatPeriod, Filename, DestinationIndex

3. Trigger: InitiateTest=1
```

### Casa C100G
```
1. BDT:  Pre-configured by CMTS — do not destroy, use docsPnmCcapBulkDataControlTable
         (docsPnmBulkDataTransferCfgTable is NOT used on Casa)

2. UTSC: Row pre-provisioned per port, cfg_index fixed by TriggerMode
         Probe cfg_index 1-3 by reading TriggerMode, write in-place
         NEVER destroy — removes DestinationIndex managed internally by CMTS
         freerun_duration HARD MAX = 300,000ms (syslog: >300000 rejected)
         freerun_duration HARD MIN = 120,000ms (syslog: <120s rejected)
         files per run (freerun/repeat) <= 300

3. Trigger: RowStatus → active(1) → InitiateTest=1
```

### Arris/CommScope E6000
```
1. BDT:  Row pre-exists — SET Protocol=1 explicitly (unlike Cisco)
2. UTSC: Row pre-exists — write params in-place (no destroy/create)
         freerun_duration max = 600,000ms (PDF: >600ms rejected)
         Max 250 files per run (MaxResultsPerFile=1 fixed)
3. Trigger: InitiateTest=1
```

---

## Key OIDs (DOCS-PNM-MIB)

| Table | OID |
|---|---|
| `docsPnmBulkDataTransferCfgTable` | `1.3.6.1.4.1.4491.2.1.27.1.1.3.1.1` |
| `docsPnmCmtsUtscCfgTable` | `1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1` |
| `docsPnmCmtsUtscCtrlTable` (InitiateTest) | `1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1` |
| `docsPnmCmtsUtscStatusTable` (MeasStatus) | `1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1` |
| Casa BDT control | `1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1` |

### UTSC Cfg Columns (suffix: `.{ifIndex}.{cfgIndex}`)

| Column | OID suffix | Type |
|---|---|---|
| LogicalChIfIndex | `.2` | `i` |
| TriggerMode | `.3` | `i` |
| CmMacAddr | `.6` | `x` |
| CenterFreq | `.8` | `u` |
| Span | `.9` | `u` |
| NumBins | `.10` | `u` |
| AvgNumber | `.11` | `u` |
| Filename | `.12` | `s` |
| OutputFormat | `.17` | `i` |
| Window | `.16` | `i` |
| RepeatPeriod | `.18` | `u` |
| FreeRunDuration | `.19` | `u` |
| TriggerCount | `.20` | `u` |
| RowStatus | `.21` | `i` |
| DestinationIndex | `.24` | `u` |

### MeasStatus Values
| Value | Meaning |
|---|---|
| 1 | other |
| 2 | inactive |
| 3 | inProgress |
| 4 | **sampleReady** |
| 5 | error |
| 6 | resourceUnavailable |
| 7 | sampleTruncated |
