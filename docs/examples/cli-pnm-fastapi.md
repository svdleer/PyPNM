# PNM Capture - FastAPI CLI Examples {#pnm-capture--fastapi-cli-examples}

Run PNM Capture Endpoints From The Command Line Using Helper Scripts.

[PNM Capture - FastAPI CLI Examples](#pnm-capture--fastapi-cli-examples)

[Overview](#overview)

[Common CLI Options](#common-cli-options)

- [Endpoint: /docs/pnm/ds/histogram/getCapture](#endpoint-docspnmdshistogramgetcapture)
- [Endpoint: /docs/pnm/ds/ofdm/fecSummary/getCapture](#endpoint-docspnmdsofdmfecsummarygetcapture)
- [Endpoint: /docs/pnm/ds/ofdm/rxMer/getCapture](#endpoint-docspnmdsofdmrxmergetcapture)
- [Endpoint: /docs/pnm/ds/ofdm/constellationDisplay/getCapture](#endpoint-docspnmdsofdmconstellationdisplaygetcapture)
- [Endpoint: /docs/pnm/ds/ofdm/modulationProfile/getCapture](#endpoint-docspnmdsofdmmodulationprofilegetcapture)
- [Endpoint: /docs/pnm/ds/ofdm/channelEstCoeff/getCapture](#endpoint-docspnmdsofdmchannelestcoeffgetcapture)
- [Endpoint: /docs/pnm/ds/spectrumAnalyzer/getCapture](#endpoint-docspnmdsspectrumanalyzergetcapture)
- [Endpoint: /docs/pnm/ds/spectrumAnalyzer/getCapture/ofdm](#endpoint-docspnmdsspectrumanalyzergetcaptureofdm)

## Overview

This guide collects the command-line helper scripts for PyPNM **PNM capture** endpoints. Each script sends a `POST`
request to the corresponding FastAPI endpoint using the same JSON payloads described in the REST documentation, so only
the CLI usage is shown here (no response payloads).

All examples assume you are running from the PyPNM project root, with the FastAPI server listening on
the [localhost API](http://127.0.0.1:8000) and SNMP community `"private"`.

## Common CLI Options

The following options are shared by most scripts:

- `--mac` / `-m` - Cable modem MAC address (for examples, use `aa:bb:cc:dd:ee:ff`)
- `--inet` / `-i` - Cable modem IPv4 address (for examples, use `192.168.0.100`)
- `--community` / `-c` - SNMP v2c community string (default: `private`)
- `--tftp-ipv4` / `-t4` - TFTP server IPv4 address (for examples, use `192.168.0.10`)
- `--tftp-ipv6` / `-t6` - TFTP server IPv6 address (default: `::1`)
- `--base-url` - FastAPI base URL (default: [localhost API](http://127.0.0.1:8000))

Endpoint-specific options are listed in each section below.

## Endpoint: /docs/pnm/ds/histogram/getCapture

Downstream Histogram PNM Capture.

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-histogram-getCapture.py`

### Example CLI Usage

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-histogram-getCapture.py  --mac aa:bb:cc:dd:ee:ff   \
                                                                            --inet 192.168.0.100    \
                                                                            --tftp-ipv4 192.168.0.10  \
                                                                            --tftp-ipv6 ::1           \
                                                                            --sample-duration 10
```

Endpoint-specific options:

- `--sample-duration` - Histogram measurement duration in seconds  
  (maps to `capture_settings.sample_duration`).

## Endpoint: /docs/pnm/ds/ofdm/fecSummary/getCapture

Downstream OFDM FEC Summary PNM Capture.

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-fecSummary-getCapture.py`

### Example CLI Usage

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-fecSummary-getCapture.py  --mac aa:bb:cc:dd:ee:ff \
                                                                                  --inet 192.168.0.100 \
                                                                                  --tftp-ipv4 192.168.0.10 \
                                                                                  --tftp-ipv6 ::1 \
                                                                                  --fec-summary-type 10min
```

Endpoint-specific options:

- `--fec-summary-type {10min,24h}` - Measurement interval:
  - `10min` → `fec_summary_type = 2` (10-minute FEC summary)
  - `24h`  → `fec_summary_type = 3` (24-hour FEC summary)

## Endpoint: /docs/pnm/ds/ofdm/rxMer/getCapture

Downstream OFDM RxMER PNM Capture.

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-rxMer-getCapture.py`

### Example CLI Usage

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-rxMer-getCapture.py --mac aa:bb:cc:dd:ee:ff \
                                                                            --inet 192.168.0.100 \
                                                                            --tftp-ipv4 192.168.0.10 \
                                                                            --tftp-ipv6 ::1
```

This script uses the default analysis settings (`type = basic`, `output.type = json`, dark UI theme) as defined in the
corresponding REST endpoint documentation.

## Endpoint: /docs/pnm/ds/ofdm/constellationDisplay/getCapture

Downstream OFDM Constellation Display PNM Capture.

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-constellationDisplay-getCapture.py`

### Example CLI Usage

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-constellationDisplay-getCapture.py --mac aa:bb:cc:dd:ee:ff \
                                                                                           --inet 192.168.0.100 \
                                                                                           --tftp-ipv4 192.168.0.10 \
                                                                                           --tftp-ipv6 ::1 \
                                                                                           --modulation-order-offset 0 \
                                                                                           --num-sample-symbols 8192
```

Endpoint-specific options:

- `--modulation-order-offset` - Profile index offset used when choosing the modulation order for plotting.
- `--num-sample-symbols` - Number of I/Q symbols to capture for the constellation display  
  (maps to `capture_settings.number_sample_symbol`).

Analysis settings follow the REST documentation for this endpoint (basic analysis, JSON output, dark theme, and
constellation plotting options).

## Endpoint: /docs/pnm/ds/ofdm/modulationProfile/getCapture

Downstream OFDM Modulation Profile PNM Capture.

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-modulationProfile-getCapture.py`

### Example CLI Usage

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-modulationProfile-getCapture.py --mac aa:bb:cc:dd:ee:ff \
                                                                                        --inet 192.168.0.100 \
                                                                                        --tftp-ipv4 192.168.0.10 \
                                                                                        --tftp-ipv6 ::1
```

This script triggers a downstream OFDM modulation profile capture using the same basic analysis configuration described
in the REST documentation.

## Endpoint: /docs/pnm/ds/ofdm/channelEstCoeff/getCapture

Downstream OFDM Channel Estimation Coefficients PNM Capture.

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-channelEstCoeff-getCapture.py`

### Example CLI Usage

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-ofdm-channelEstCoeff-getCapture.py --mac aa:bb:cc:dd:ee:ff \
 \                                                                                         --inet 192.168.0.100 \
                                                                                          --tftp-ipv4 192.168.0.10 \
                                                                                          --tftp-ipv6 ::1
```

The JSON response schema is identical to the REST documentation for this endpoint (full OFDM channel estimation model).

## Endpoint: /docs/pnm/ds/spectrumAnalyzer/getCapture

Downstream Spectrum Analyzer PNM Capture (Segment Sweep).

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-spectrumAnalyzer-getCapture.py`

### Example CLI Usage

Segment sweep using defaults for the capture window:

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-spectrumAnalyzer-getCapture.py   --mac aa:bb:cc:dd:ee:ff \
                                                                                    --inet 192.168.0.100 \
                                                                                    --tftp-ipv4 192.168.0.10 \
                                                                                    --tftp-ipv6 ::1 \
                                                                                    --retrieval-type file \
                                                                                    --http-timeout 180
```

Endpoint-specific options:

- `--retrieval-type {file,snmp}` - How spectrum data is retrieved:
  - `file` → Retrieve spectrum via PNM file (TFTP).
  - `snmp` → Retrieve spectrum directly via SNMP.
- `--http-timeout` - HTTP timeout in seconds for the FastAPI request (default: `180`).

Capture parameter defaults in the script mirror the REST example (first and last segment center frequency, segment span,
number of bins, noise bandwidth, window function, number of averages, and inactivity timeout). Use the script’s
`--help` to override them if needed.

## Endpoint: /docs/pnm/ds/spectrumAnalyzer/getCapture/ofdm

Downstream Spectrum Analyzer PNM Capture (OFDM Aligned).

- **Script:** `src/pypnm/examples/fast_api/api-docs-pnm-ds-spectrumAnalyzer-getCapture-ofdm.py`

### Example CLI Usage

OFDM-aligned spectrum across the active OFDM channel:

```bash
python src/pypnm/examples/fast_api/api-docs-pnm-ds-spectrumAnalyzer-getCapture-ofdm.py   --mac aa:bb:cc:dd:ee:ff \
                                                                                        --inet 192.168.0.100 \
                                                                                        --tftp-ipv4 192.168.0.10 \
                                                                                        --tftp-ipv6 ::1 \
                                                                                        --retrieval-type file \
                                                                                        --num-averages 1 \
                                                                                        --http-timeout 180
```

Endpoint-specific options:

- `--retrieval-type {file,snmp}` - File-based PNM or direct SNMP retrieval (same semantics as the segment sweep).
- `--num-averages` - Number of averages used when generating the OFDM-aligned spectrum  
  (maps to `capture_parameters.number_of_averages`).
- `--http-timeout` - HTTP timeout in seconds for the FastAPI request (default: `180`).

The script configures the analysis block with `type = basic`, JSON output, dark theme, and optional moving-average
smoothing under `analysis.spectrum_analysis.moving_average.points`, matching the REST example for this endpoint.
