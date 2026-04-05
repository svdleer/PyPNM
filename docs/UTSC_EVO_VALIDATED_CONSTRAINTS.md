bu# UTSC CommScope EVO vCCAP — Validated Constraints (2026-04-05)

## Test Environment
- **Device**: MND-GT0002-CCAPV001 (Casa DCTS vCCAP, firmware 10.10.0)
- **IP**: 172.16.6.160
- **Test Date**: April 5, 2026

---

## Critical Constraint: FreeRunning File Count

### **CASA/EVO Firmware Limit**
```
FreeRunDuration / RepeatPeriod <= 300 files (absolute maximum)
```

### Error Message (When Violated)
```
[timestamp] ER-SNMP-1: cp0: snmpd(pid=...): utsc_freerun_param_check() 
freerun capture file number error {actual_count}, max file number:300
```

### Safe Parameters
| Duration | Min RepeatPeriod | File Count | Status |
|----------|------------------|-----------|--------|
| 120s | 400ms | 300 | ✅ Valid (at limit) |
| 120s | 500ms | 240 | ✅ Safe margin |
| 120s | 100ms | 1200 | ❌ **REJECTED** |
| 300s | 1000ms | 300 | ✅ At limit |

### Formula
```
files = FreeRunDuration_ms / RepeatPeriod_ms
required_repeat_period = FreeRunDuration_ms / 300
```

---

## Validated Parameter Ranges (EVO 10.10.0)

| Parameter | Min | Default | Max | Notes |
|-----------|-----|---------|-----|-------|
| **CenterFreq** | 5 MHz | 50 MHz | 200 MHz | Must be even multiple of 50 kHz |
| **Span** | 40 MHz | 80 MHz | 320 MHz | Supported: 40, 80, 160, 320 MHz only |
| **NumBins** | 200 | 800 | 3200 | E6000 valid: 200, 400, 800, 1600, 3200 |
| **RepeatPeriod** | 100 ms | **400 ms** | 60 s | Store as µs: `400_000` = 400ms |
| **FreeRunDuration** | 120 s | 120 s | 300 s | Store as ms: `120_000` = 120s |
| **TriggerCount** | 1 | 10 | 10 | Ignored in freeRunning mode |
| **LogicalChIfIndex** | 0 | 0 | any | 0 = all OFDMA; else pin to 160001280+ |

---

## EVO Configuration Quirks

### Config Index (Table Key Strategy)
- **RF Port**: Use 120001280 (RPHY Upstream Physical Interface)
- **Config Index**: Try indices **2, 3, 1** in that order (not guaranteed to exist)
- **Why**: EVO allocates indices per port; not sequential or predictable
- **Workaround**: Fall back to next index if first fails

### Row Lifecycle Behavior
```
1. createAndGo(4) → Accepted ✅
2. Set parameters while createAndGo completes
3. RowStatus reads active(1) after success
4. Note: May read createAndWait(5) but still works
```

### TriggerMode Support
- **freeRunning(2)**: ✅ Works **IF** file count valid (see CRITICAL constraint above)
- **idleSid(5)**: ✅ Always works, but captures run forever (no sampleReady signal)
- **Capability check**: BITS: 40 00 = freeRunning advertised

### Fixed Issues (Don't These Again)
| Issue | Cause | Fix |
|-------|-------|-----|
| "freerun file number error 1200" | RepeatPeriod too small (100ms) | Increase to 400ms |
| DestinationIndex commitFailed | BDT selector bits not set | Use autoUpload(3) + bits 0080 |
| InitiateTest commitFailed | Row not fully active or file count invalid | Fix file count first |
| MeasStatus always inactive | Capture never started (params invalid) | Validate file count + RF port |

---

## Parameter Inheritance

### PyPNMGui UTSC Validation
**File**: `backend/app/core/utsc_validation.py`
- **Function**: `validate_all_parameters()` — now includes file count check
- **Added**: `file_count` field in returned dict
- **Error message**: Auto-suggests minimum RepeatPeriod if file count exceeds 300

### PyPNM Provision Scripts
**Files**:
- `scripts/provision_utsc.py` — Casa 100G / EVO generic
- `scripts/provision_utsc_evo.py` — EVO-specific workarounds

**Default changes**:
- `REPEAT_PERIOD`: 100ms → **400ms** (satisfies file count constraint)
- Added validation comment in docstring

---

## Deployment Checklist

- [ ] Update PyPNMGui `utsc_validation.py` with file count validation ✅ Done
- [ ] Update `provision_utsc.py` REPEAT_PERIOD to 400ms ✅ Done
- [ ] Update `provision_utsc_evo.py` with validated constraints ✅ Done
- [ ] Add EVO notes to validation docstring ✅ Done
- [ ] Test with RepeatPeriod values: 400ms, 500ms, 600ms
- [ ] Test with FreeRunDuration: 120s, 150s, 200s
- [ ] Verify file count never exceeds 300 before sending to CMTS

---

## References

- [UTSC SNMP Commands Reference](./UTSC_SNMP_COMMANDS.md)
- [provision_utsc_evo.py](../scripts/provision_utsc_evo.py) — Working example
- MIB: docsPnmCmtsUtscCfg (DOCS-PNM-MIB)
- Casa E6000 CER User Guide Release 13.0
