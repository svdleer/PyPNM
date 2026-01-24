# Single capture operations

Endpoints that perform one-shot capture or query against a single device. All routes live under the FastAPI service (default [localhost API](http://127.0.0.1:8000)). Use the [request](../common/request.md) and [response](../common/response.md) conventions when constructing payloads.

## Choose a telemetry path

### Downstream SNMP telemetry

Poll DOCSIS 3.0/3.1 downstream metrics directly from the cable modem via SNMP-backed endpoints.

| Reference | Purpose |
|-----------|---------|
| [OFDM channel statistics](ds/ofdm/channel-stats.md) | Snapshot OFDM physical channel KPIs. |
| [OFDM profile statistics](ds/ofdm/profile-stats.md) | Codeword stats per OFDM profile. |
| [SC-QAM channel statistics](ds/scqam/channel-stats.md) | SC-QAM downstream power/SNR stats. |
| [SC-QAM CW error rate](ds/scqam/cw-error-rate.md) | Codeword error counters. |

### Upstream SNMP telemetry

| Reference | Purpose |
|-----------|---------|
| [OFDMA channel statistics](us/ofdma/stats.md) | OFDMA upstream channel KPIs. |
| [ATDMA pre-equalization](us/atdma/chan/pre-equalization.md) | Tap coefficients and equalizer status. |
| [ATDMA channel statistics](us/atdma/chan/stats.md) | ATDMA upstream power/SNR stats. |

### FDD / FDX diplexer info

| Reference | Purpose |
|-----------|---------|
| [Diplexer band-edge capability](fdd/fdd-diplexer-band-edge-cap.md) | Supported diplexer range. |
| [Diplexer configuration (system)](fdd/fdd-system-diplexer-configuration.md) | System-level diplexer settings. |

### Cable modem utilities

| Reference | Purpose |
|-----------|---------|
| [Diplexer configuration](general/diplexer-configuration.md) | Device-level diplexer settings. |
| [DOCSIS base configuration](general/docsis-base-configuration.md) | Full DOCSIS configuration snapshot. |
| [Event log](general/event-log.md) | Retrieve the CM event log. |
| [Reset cable modem](general/reset-cm.md) | Invoke a remote reset. |
| [System description](general/system-description.md) | SNMP `sysDescr`. |
| [System uptime](general/up-time.md) | SNMP `sysUpTime`. |
| [Interface statistics](pnm/interface/stats.md) | Interface-level counters. |

## Proactive network maintenance (PNM)

### Downstream captures

| Reference | Purpose |
|-----------|---------|
| [OFDM RxMER](ds/ofdm/rxmer.md) | Raw RxMER, summaries, plots. |
| [OFDM MER margin](ds/ofdm/mer-margin.md) | MER margin helpers. |
| [OFDM channel estimation](ds/ofdm/channel-estimation.md) | Echo/distortion analysis. |
| [OFDM constellation display](ds/ofdm/constellation-display.md) | Symbol visualization. |
| [OFDM FEC summary](ds/ofdm/fec-summary.md) | Forward error correction stats. |
| [OFDM modulation profile](ds/ofdm/modulation-profile.md) | Bit loading and usage. |
| [Histogram](ds/histogram.md) | Power-level histogram. |

### Upstream captures

| Reference | Purpose |
|-----------|---------|
| [OFDMA pre-equalization](us/ofdma/pre-equalization.md) | Upstream tap coefficients. |

## Spectrum analysis

| Reference | Purpose |
|-----------|---------|
| [Spectrum analyzer endpoints](spectrum-analyzer/spectrum-analyzer.md) | Capture downstream spectrum snapshots (SC-QAM and OFDM options within). |
| [Spectrum analyzer RBW permutations](spectrum-analyzer.md) | Reference RBW auto-scale outcomes for common and edge-case spans. |
