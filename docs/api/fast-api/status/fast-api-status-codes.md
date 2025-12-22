# ServiceStatusCode

Note: This is a subset of codes for quick reference. For the complete, authoritative list, see the source:
[`src/pypnm/api/routes/common/service/status_codes.py`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/api/routes/common/service/status_codes.py)

## Connection and control

| Code name          | Value | Notes                               |
|--------------------|------:|-------------------------------------|
| `SUCCESS`          |     0 | Operation completed successfully.   |
| `UNREACHABLE_PING` |     1 | Device not reachable via ICMP ping. |
| `UNREACHABLE_SNMP` |     2 | Device not reachable via SNMP.      |
| `FAILURE`          |    17 | Generic failure.                    |
| `PING_FAILED`      |    19 | Ping attempt failed.                |

## File setup and retrieval

| Code name                                | Value | Notes                                                  |
|------------------------------------------|------:|--------------------------------------------------------|
| `FILE_SET_FAIL`                          |     6 | Failed to set capture filename on the device.          |
| `TEST_ERROR`                             |     7 | Generic error during test/capture.                     |
| `MEASUREMENT_TIMEOUT`                    |     8 | Measurement timed out waiting for readiness.           |
| `TFTP_SERVER_PATH_SET_FAIL`              |     9 | Failed to set TFTP server address/path on the device.  |
| `NOT_READY_AFTER_FILE_CAPTURE`           |    10 | Device did not return to READY state after capture.    |
| `COPY_PNM_FILE_TO_LOCAL_SAVE_DIR_FAILED` |    11 | Local copy of captured PNM file failed.                |
| `TFTP_PNM_FILE_UPLOAD_FAILURE`           |    21 | Device → server upload to TFTP failed.                 |

## Feature availability

| Code name                          | Value | Notes                                         |
|------------------------------------|------:|-----------------------------------------------|
| `DS_OFDM_RXMER_NOT_AVAILABLE`      |   300 | Downstream OFDM RxMER not available.          |
| `SPEC_ANALYZER_NOT_AVAILABLE`      |   400 | Spectrum analyzer not available.              |
| `DS_OFDM_MULIT_RXMER_FAILED`       |   500 | Downstream OFDM multi-RxMER failed.           |
| `DS_OFDM_CHAN_EST_NOT_AVAILABLE`   |   600 | Downstream OFDM channel estimation unavailable. |
| `DS_OFDM_FEC_SUMMARY_NOT_AVALIABLE`|   700 | Downstream OFDM FEC summary unavailable.      |
| `DS_OFDM_MOD_PROFILE_NOT_AVALAIBLE`|   800 | Downstream OFDM modulation profile unavailable. |

## Parameters and prerequisites

| Code name                        | Value | Notes                                    |
|----------------------------------|------:|------------------------------------------|
| `NO_SPECTRUM_CAPTURE_PARAMETERS` |  1000 | Required spectrum capture parameters missing. |
