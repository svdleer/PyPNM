# PyPNM Python API - PNM Parser Usage Examples

This guide shows how to use the PyPNM binary parsers directly from Python and via the
example CLI scripts under:

`src/pypnm/examples/python/parsers/`

All examples assume:

- You are in the project root: `~/Projects/PyPNM`
- Test fixtures are available in: `tests/files/`
- Your virtual environment is active.

## Table Of Contents

[Overview](#overview)

[Common Parser API Pattern](#common-parser-api-pattern)

[Downstream OFDM Parsers](#downstream-ofdm-parsers)

- [3.1 Downstream OFDM RxMER](#ds-ofdm-rxmer)
- [3.2 Downstream OFDM Channel Estimation](#ds-ofdm-chan-est)
- [3.3 Downstream OFDM FEC Summary](#ds-ofdm-fec-summary)
- [3.4 Downstream OFDM Modulation Profile](#ds-ofdm-modulation-profile)

[Spectrum Analysis Parsers](#spectrum-analysis-parsers)

- [4.1 PNM Spectrum Analyzer](#ds-spectrum-analysis)
- [4.2 SNMP Spectrum Analyzer (AmplitudeData)](#ds-spectrum-analysis-snmp)

[Upstream OFDMA Pre-Equalization Parsers](#upstream-ofdma-pre-equalization-parsers)

- [5.1 Upstream OFDMA Pre-Equalization](#us-ofdma-preeq)
- [5.2 Upstream OFDMA Pre-Equalization Last Update](#us-ofdma-preeq-last-update)

[Programming Patterns And Integration Notes](#programming-patterns-and-integration-notes)

## Overview

The examples in this directory exercise the binary parsers that turn raw PNM capture files
into typed Pydantic models. Each parser focuses on a specific DOCSIS PNM payload.

Representative parser classes:

- [`CmDsOfdmRxMer`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmRxMer.py)
- [`CmDsOfdmChanEstimateCoef`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py)
- [`CmDsOfdmFecSummary`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmFecSummary.py)
- [`CmDsOfdmModulationProfile`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmModulationProfile.py)
- [`CmSpectrumAnalysis`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmSpectrumAnalysis.py)
- [`CmSpectrumAnalysisSnmp`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmSpectrumAnalysisSnmp.py)
- [`CmUsOfdmaPreEq`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmUsOfdmaPreEq.py)

Each example script loads a test capture from `tests/files/`, parses it into the appropriate
model, and prints `model_dump_json(indent=2)` to stdout.

The example scripts live here:

- `src/pypnm/examples/python/parsers/pnm-ds-rxmer.py`
- `src/pypnm/examples/python/parsers/pnm-ds-chan-est-coeff.py`
- `src/pypnm/examples/python/parsers/pnm-ds-fec-summary.py`
- `src/pypnm/examples/python/parsers/pnm-ds-modulation-profile.py`
- `src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis.py`
- `src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis-snmp.py`
- `src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq.py`
- `src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq-last-update.py`

## Common Parser API Pattern

All parser classes follow the same basic pattern:

- Constructor accepts a `bytes` payload.
- Internal parsing/validation happens in `__init__`.
- Results are exposed via:

| Method       | Return Type                     | Description                                               |
|-------------|----------------------------------|-----------------------------------------------------------|
| `to_model()` | Typed Pydantic model (`*Model`) | Return the fully validated PNM model.                    |
| `to_dict()`  | `dict[str, Any]`               | Convenience wrapper for `model_dump()`.                  |
| `to_json()`  | `str`                           | Convenience wrapper for `model_dump_json(indent=...)`.   |

Typical usage:

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmRxMer import CmDsOfdmRxMer, CmDsOfdmRxMerModel

pfile = Path("tests/files/rxmer.bin")
raw_payload: bytes = FileProcessor(pfile).read_file()

parser = CmDsOfdmRxMer(raw_payload)
model: CmDsOfdmRxMerModel = parser.to_model()

print(model.model_dump_json(indent=2))
```

The example CLI scripts only wrap this pattern in a `main()` function and hard-code the
input path to the test fixture.

## Downstream OFDM Parsers

<a id="ds-ofdm-rxmer"></a>
### 3.1 Downstream OFDM RxMER - pnm-ds-rxmer.py

Script:

- `src/pypnm/examples/python/parsers/pnm-ds-rxmer.py`

Parser:

- [`CmDsOfdmRxMer`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmRxMer.py)

Input PNM file:

- `tests/files/rxmer.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-ds-rxmer.py
```

The script will:

1. Read `tests/files/rxmer.bin`.
2. Decode it with `CmDsOfdmRxMer`.
3. Print the `CmDsOfdmRxMerModel` as prettified JSON.

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmRxMer import CmDsOfdmRxMer, CmDsOfdmRxMerModel

pfile = Path("tests/files/rxmer.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmDsOfdmRxMer(raw_payload)
rxmer_model: CmDsOfdmRxMerModel = parser.to_model()

subcarrier_mer = rxmer_model.rxmer_values  # example field name
print(f"Number of subcarriers: {len(subcarrier_mer)}")
```

You can feed `rxmer_model` into downstream analysis functions (for example, RxMER statistics
or profile-aligned plots).

<a id="ds-ofdm-chan-est"></a>
### 3.2 Downstream OFDM Channel Estimation - pnm-ds-chan-est-coeff.py

Script:

- `src/pypnm/examples/python/parsers/pnm-ds-chan-est-coeff.py`

Parser:

- [`CmDsOfdmChanEstimateCoef`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py)

Input fixture:

- `tests/files/channel_estimation.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-ds-chan-est-coeff.py
```

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmChanEstimateCoef import (
    CmDsOfdmChanEstimateCoef,
    CmDsOfdmChanEstimateCoefModel,
)

pfile = Path("tests/files/channel_estimation.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmDsOfdmChanEstimateCoef(raw_payload)
chan_est_model: CmDsOfdmChanEstimateCoefModel = parser.to_model()

tap_values = chan_est_model.values
print(f"Total taps: {len(tap_values)}")
```

Channel estimation taps can be used as input to echo detection, group delay analysis, or
other RF impairment tools.

<a id="ds-ofdm-fec-summary"></a>
### 3.3 Downstream OFDM FEC Summary - pnm-ds-fec-summary.py

Script:

- `src/pypnm/examples/python/parsers/pnm-ds-fec-summary.py`

Parser:

- [`CmDsOfdmFecSummary`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmFecSummary.py)

Input fixture:

- `tests/files/fec_summary.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-ds-fec-summary.py
```

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmFecSummary import CmDsOfdmFecSummary, CmDsOfdmFecSummaryModel

pfile = Path("tests/files/fec_summary.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmDsOfdmFecSummary(raw_payload)
fec_model: CmDsOfdmFecSummaryModel = parser.to_model()

print(f"Total codewords: {fec_model.total_codewords}")
print(f"Corrected codewords: {fec_model.corrected_codewords}")
print(f"Uncorrectable codewords: {fec_model.uncorrectable_codewords}")
```

<a id="ds-ofdm-modulation-profile"></a>
### 3.4 Downstream OFDM Modulation Profile - pnm-ds-modulation-profile.py

Script:

- `src/pypnm/examples/python/parsers/pnm-ds-modulation-profile.py`

Parser:

- [`CmDsOfdmModulationProfile`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmModulationProfile.py)

Input fixture:

- `tests/files/modulation_profile.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-ds-modulation-profile.py
```

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmDsOfdmModulationProfile import CmDsOfdmModulationProfile
from pypnm.pnm.parser.model.parser_rtn_models import CmDsOfdmModulationProfileModel

pfile = Path("tests/files/modulation_profile.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmDsOfdmModulationProfile(raw_payload)
profile_model: CmDsOfdmModulationProfileModel = parser.to_model()

for profile in profile_model.modulation_profiles:
    print(f"Profile ID: {profile.profile_id}, Modulation: {profile.modulation_order}")
```

Modulation profiles can be correlated with RxMER and FEC statistics to understand how
modulation is allocated across the OFDM channel.

## Spectrum Analysis Parsers

<a id="ds-spectrum-analysis"></a>
### 4.1 PNM Spectrum Analyzer - pnm-ds-spectrum-analysis.py

Script:

- `src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis.py`

Parser:

- [`CmSpectrumAnalysis`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmSpectrumAnalysis.py)

Input fixture:

- `tests/files/spectrum_analyzer.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis.py
```

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmSpectrumAnalysis import CmSpectrumAnalysis, CmSpectrumAnalyzerModel

pfile = Path("tests/files/spectrum_analyzer.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmSpectrumAnalysis(raw_payload)
spec_model: CmSpectrumAnalyzerModel = parser.to_model()

print(f"Bins per segment: {spec_model.num_bins_per_segment}")
print(f"Number of segments: {len(spec_model.amplitude_bin_segments_float)}")
```

You can feed `spec_model.amplitude_bin_segments_float` into plotting utilities to visualize
per-segment spectra or stitch them into a full-band sweep.

<a id="ds-spectrum-analysis-snmp"></a>
### 4.2 SNMP Spectrum Analyzer (AmplitudeData) - pnm-ds-spectrum-analysis-snmp.py

Script:

- `src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis-snmp.py`

Parser:

- [`CmSpectrumAnalysisSnmp`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmSpectrumAnalysisSnmp.py)

Input fixture:

- `tests/files/spectrum_analyzer_snmp.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-ds-spectrum-analysis-snmp.py
```

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmSpectrumAnalysisSnmp import (
    CmSpectrumAnalysisSnmp,
    CmSpectrumAnalysisSnmpModel,
)

pfile = Path("tests/files/spectrum_analyzer_snmp.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmSpectrumAnalysisSnmp(raw_payload)
snmp_spec_model: CmSpectrumAnalysisSnmpModel = parser.to_model()

print(f"Total samples: {snmp_spec_model.total_samples}")
print(f"Start frequency: {snmp_spec_model.spectrum_config.start_frequency} Hz")
print(f"End frequency: {snmp_spec_model.spectrum_config.end_frequency} Hz")
```

The SNMP version is especially useful when the CM only exposes sweep data via the
`docsIf3CmSpectrumAnalysisMeasAmplitudeData` object.

## Upstream OFDMA Pre-Equalization Parsers

<a id="us-ofdma-preeq"></a>
### 5.1 Upstream OFDMA Pre-Equalization - pnm-us-ofdma-preeq.py

Script:

- `src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq.py`

Parser:

- [`CmUsOfdmaPreEq`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmUsOfdmaPreEq.py)

Input fixture:

- `tests/files/us_pre_equalizer_coef.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq.py
```

#### Programmatic Usage

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmUsOfdmaPreEq import CmUsOfdmaPreEq, CmUsOfdmaPreEqModel

pfile = Path("tests/files/us_pre_equalizer_coef.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmUsOfdmaPreEq(raw_payload)
preeq_model: CmUsOfdmaPreEqModel = parser.to_model()

print(f"Channel ID: {preeq_model.channel_id}")
print(f"Tap count: {len(preeq_model.values)}")
```

Upstream pre-equalization coefficients are the foundation for group delay, echo detection,
and upstream impairment analysis.

<a id="us-ofdma-preeq-last-update"></a>
### 5.2 Upstream OFDMA Pre-Equalization Last Update - pnm-us-ofdma-preeq-last-update.py

Script:

- `src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq-last-update.py`

Parser:

- Same parser class [`CmUsOfdmaPreEq`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmUsOfdmaPreEq.py),
  but operating on the `UPSTREAM_PRE_EQUALIZER_COEFFICIENTS_LAST_UPDATE` PNM file type.

Input fixture:

- `tests/files/us_pre_equalizer_coef_last.bin`

#### CLI Usage

```bash
cd ~/Projects/PyPNM

python3 src/pypnm/examples/python/parsers/pnm-us-ofdma-preeq-last-update.py
```

#### Programmatic Usage

The usage is identical to the full pre-equalizer capture; only the input file and
underlying PNM file type differ.

```python
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmUsOfdmaPreEq import CmUsOfdmaPreEq, CmUsOfdmaPreEqModel

pfile = Path("tests/files/us_pre_equalizer_coef_last.bin")
raw_payload = FileProcessor(pfile).read_file()

parser = CmUsOfdmaPreEq(raw_payload)
last_update_model: CmUsOfdmaPreEqModel = parser.to_model()

print(f"Tap count (last update): {len(last_update_model.values)}")
```

## Programming Patterns And Integration Notes

- All parser examples assume you are working with **offline captures** stored under
  `tests/files/`. In production, these bytes typically come from PNM bulk data transfers,
  TFTP, HTTP, or direct SNMP responses.
- The general flow is always:

  1. Acquire bytes (`bytes`) for a given PNM capture.
  2. Pass them into the parser constructor.
  3. Use `.to_model()` to obtain a typed model.
  4. Pass the model into analysis, visualization, or FastAPI response payloads.

- The same parser classes used here are also used internally by the FastAPI endpoints in
  the `pypnm.api.routes` tree, so behavior is consistent between CLI, Python API, and REST.

With these examples in place, you can use the PyPNM parsers either as quick CLI tools
for inspecting PNM files or as building blocks in larger analysis workflows.
