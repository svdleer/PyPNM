# Spectrum analyzer — downstream spectrum captures

Parser and helper for SC-QAM and OFDM spectrum snapshots captured through the spectrum analyzer endpoint.

> **Module location**
> `src/pypnm/pnm/parser/CmSpectrumAnalyzer.py`

## Inputs

- Raw spectrum capture payload (`ds_spectrum_scqam.bin`, `ds_spectrum_ofdm.bin`, etc.).
- Analyzer metadata (center frequency, span) is embedded in the binary header.

## Outputs

- `CmSpectrumAnalyzerModel.header`: sweep configuration (start/stop frequency, resolution, capture time).
- `samples_dbmv`: list of power readings per bin.
- `frequencies_hz`: matching frequency axis.

## Usage

```python
from pathlib import Path
from pypnm.pnm.parser.CmSpectrumAnalyzer import CmSpectrumAnalyzer

payload = Path("spectrum.bin").read_bytes()
spectrum = CmSpectrumAnalyzer(payload)

dbmv = spectrum.get_samples()
frequencies = spectrum.get_frequencies()
```
