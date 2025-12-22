# Proactive network maintenance (PNM)

Python helpers for decoding DOCSIS PNM binaries and running signal-processing workflows.

> **Before you start**
> - Install PyPNM with extras (`pip install -e .[dev,docs]`) so NumPy/SciPy dependencies are present.
> - PNM decoders expect raw files captured via the FastAPI workflows or stored under `.data/pnm`. Use the [file manager API](../../fast-api/file-manager/file-manager-api.md) to fetch them if needed.

## File formats and decoding

| Guide | Description |
|-------|-------------|
| [PNM processing](processing/pnm-processing.md) | Links to each parser/decoder (RxMER, channel estimation, modulation profiles, etc.). |

## Signal processing helpers

| Guide | Description |
|-------|-------------|
| [Butterworth smoothing](signal-processing/butterworth.md) | Low-pass filtering for OFDM coefficients and diagnostics. |
| [Echo detection](signal-processing/echo-detection.md) | FFT/IFFT-based time-domain analysis of OFDM coefficients. |
| [Moving average](signal-processing/moving-average.md) | Simple moving average for OFDM and spectrum diagnostics. |
