# Butterworth Smoothing for OFDM Pre-Equalization and Channel Estimation

This note explains how PyPNM uses a low-pass Butterworth filter to smooth OFDM-domain
coefficients, both complex (pre-equalization or channel estimation taps) and scalar
series (for example, RxMER per subcarrier). It focuses on the math and interpretation
first, then ends with a minimal code example using the `PreEqButterworthFilter` and
`MagnitudeButterworthFilter` helpers.

## 1. Signal Model and Sampling Along Subcarriers

For an OFDM upstream channel, we assume a set of uniformly spaced subcarriers with
spacing

\[
\Delta f = \text{subcarrier\_spacing\_hz} \; [\text{Hz}] .
\]

We treat any per-subcarrier series as samples of a 1D discrete-time signal in the
"subcarrier index" domain. For a complex coefficient vector

\[
x[k], \quad k = 0, 1, \dots, N-1,
\]

you can think of \(k\) as the sample index and \(\Delta f\) as the effective
sample rate in Hertz along that index. This is the key mapping:

- **Sample index**: subcarrier index \(k\)
- **Sample rate**: \(f_s = \Delta f\)
- **Sample period**: \(T_s = 1 / f_s\)

With this mapping, we can use standard 1D digital filtering on \(x[k]\), even
though the underlying domain is frequency (subcarriers) rather than time.

## 2. Discrete-Time Butterworth Low-Pass Filter

A digital Butterworth low-pass filter of order \(n\) has a maximally flat magnitude
response in the passband, and monotonically decaying magnitude in the stopband.

In the discrete-time domain, the filter is implemented as an IIR filter with transfer
function

\[
H(z) = \frac{\sum_{m=0}^{n} b_m z^{-m}}{1 + \sum_{m=1}^{n} a_m z^{-m}},
\]

so the filtered output \(y[k]\) satisfies the difference equation

\[
y[k] = \sum_{m=0}^{n} b_m x[k - m] - \sum_{m=1}^{n} a_m y[k - m].
\]

The coefficients \(\{b_m\}\) and \(\{a_m\}\) are chosen so that the magnitude
response \(|H(e^{j\omega})|\) approximates the ideal low-pass shape with a given
cutoff frequency and order.

## 3. Normalized Cutoff and Nyquist Frequency

For a real sample rate \(f_s\), the Nyquist frequency is

\[
f_N = \frac{f_s}{2}.
\]

SciPy's `butter` function expects the cutoff specified as a **normalized frequency**
in the range \(0 < W_n < 1\), where

\[
W_n = \frac{f_c}{f_N} = \frac{f_c}{f_s / 2} = \frac{2 f_c}{f_s}.
\]

In the PyPNM filter helpers, we compute

- `sample_rate_hz = f_s`
- `cutoff_hz = f_c`
- `normalized = cutoff_hz / (sample_rate_hz / 2)`

and validate that

\[
0 < \text{normalized} < 1 ,
\]

otherwise the configuration is considered invalid.

Because we interpret `sample_rate_hz` as the subcarrier spacing \(\Delta f\),
the cutoff \(f_c\) is expressed in the *same units* (Hertz) and directly controls
how quickly the filter responds to variation across subcarriers.

## 4. Complex vs Real-Valued Filtering

The same Butterworth design can be applied to:

- **Complex-valued series**: pre-equalization taps or channel estimates \(H[k]\)
- **Real-valued series**: magnitude, RxMER, SNR, or any scalar diagnostic series

### 4.1 Complex Coefficients

For complex coefficients \(x[k] \in \mathbb{C}\), SciPy applies the real-valued
IIR filter independently to the real and imaginary parts:

\[
\Re\{y[k]\} = (b * \Re\{x\})[k], \quad
\Im\{y[k]\} = (b * \Im\{x\})[k],
\]

with the same denominator coefficients \(a_m\). This is exactly what we want for
smoothing complex taps: both components are filtered consistently and the resulting
complex vector remains aligned in phase and amplitude.

### 4.2 Real-Valued Series

For real-valued series \(x[k] \in \mathbb{R}\), the same filter acts on the scalar
samples directly. This is useful for:

- Smoothing noisy RxMER traces, without over-smoothing genuine tilt or notches.
- Smoothing magnitude-only views of channel estimation data.

## 5. Zero-Phase Filtering vs Causal Filtering

The filters support two modes:

1. **Zero-phase filtering** (`zero_phase = True`)
   - Implemented via `scipy.signal.filtfilt(b, a, x)`.
   - The filter is run forward and backward, canceling phase distortion.
   - Effective magnitude response is squared, but the phase is approximately zero.
   - This is ideal for *analysis plots* and offline diagnostics, where causality is
     not required and symmetry is desirable.

2. **Causal filtering** (`zero_phase = False`)
   - Implemented via `scipy.signal.lfilter(b, a, x)`.
   - Standard IIR filter with nonzero phase response.
   - More appropriate when simulating real-time behavior, or when you want to
     mimic what a real device could implement.

In PyPNM, the default is `zero_phase = True` to emphasize interpretability of
diagnostic plots (magnitude, group delay, and complex scatter).

## 6. Choosing Cutoff and Order for OFDM Pre-Equalization

There is no single correct cutoff; it depends on how aggressively you want to
smooth plant behavior vs. noise. A few guidelines:

- Let \(f_s = \Delta f\) be your subcarrier spacing (for example, 50 kHz).
- Start with **moderate order** (for example, 4) to avoid excessive ringing.
- Choose a cutoff \(f_c\) as a fraction of the Nyquist frequency, such as:

  - Gentle smoothing: \(f_c \approx 0.6 f_N\)
  - Aggressive smoothing: \(f_c \approx 0.3 f_N\)

Given \(f_s = 50\,\text{kHz}\), the Nyquist frequency is \(25\,\text{kHz}\).
If you pick \(f_c = 7.5\,\text{kHz}\), then

\[
\text{normalized} = \frac{f_c}{f_N} = \frac{7.5\,\text{kHz}}{25\,\text{kHz}} = 0.3 .
\]

This produces a filter that strongly suppresses rapid variation from one
subcarrier to the next, while preserving slower trends (for example, tilt).

## 7. Summary of Helper Models

PyPNM provides the following models for Butterworth-based smoothing:

- `PreEqButterworthConfig`
  - Defines `sample_rate_hz`, `cutoff_hz`, `order`, and `zero_phase`.
- `PreEqButterworthFilter`
  - Applies the filter to complex coefficient arrays and returns a
    `PreEqButterworthResult` with original and filtered coefficients.
- `MagnitudeButterworthFilter`
  - Applies the filter to real-valued arrays and returns a
    `MagnitudeButterworthResult` with original and filtered values.

These helpers are thin wrappers around SciPy and NumPy, but they embed
domain-specific semantics (subcarrier spacing, OFDM context, and type safety)
to keep analysis code clear and consistent.

## 8. Simple Implementation Example

Below is a self-contained example showing both complex and real-valued filtering
using the PyPNM helpers described above. It assumes you have already imported
and wired the classes from `pypnm.lib` as in your project.

```python
import numpy as np

from pypnm.lib.types import FrequencyHz, NDArrayC128, NDArrayF64
from pypnm.lib.signal_processing.preeq_butterworth import (
    PreEqButterworthFilter,
    MagnitudeButterworthFilter,
)

# Example OFDM parameters
subcarrier_spacing_hz: FrequencyHz = 50_000.0   # 50 kHz
cutoff_hz:            FrequencyHz = 7_500.0     # 7.5 kHz (0.3 * Nyquist)

# ----------------------------------------------------------------------
# 1. Complex pre-equalization coefficients (e.g. H[k] or pre-EQ taps)
# ----------------------------------------------------------------------
num_subcarriers = 1024
k = np.arange(num_subcarriers, dtype=float)

# Synthetic complex series with slow trend + noise
slow_trend = 0.5 * np.exp(1j * 2.0 * np.pi * k / num_subcarriers)
noise      = 0.1 * (np.random.randn(num_subcarriers) + 1j * np.random.randn(num_subcarriers))
coeffs: NDArrayC128 = slow_trend + noise

# Construct and apply the complex-domain Butterworth filter
pre_eq_filter = PreEqButterworthFilter.from_subcarrier_spacing(
    subcarrier_spacing_hz = subcarrier_spacing_hz,
    cutoff_hz             = cutoff_hz,
    order                 = 4,
    zero_phase            = True,
)

pre_eq_result = pre_eq_filter.apply(coefficients=coeffs)

print("Complex coefficients:")
print("  original shape:", pre_eq_result.original_coefficients.shape)
print("  filtered shape:", pre_eq_result.filtered_coefficients.shape)

# ----------------------------------------------------------------------
# 2. Real-valued series (e.g. RxMER per subcarrier)
# ----------------------------------------------------------------------
rxmer_db: NDArrayF64 = 40.0 + 2.0 * np.sin(2.0 * np.pi * k / 256.0) + 0.5 * np.random.randn(num_subcarriers)

mag_filter = MagnitudeButterworthFilter.from_subcarrier_spacing(
    subcarrier_spacing_hz = subcarrier_spacing_hz,
    cutoff_hz             = cutoff_hz,
    order                 = 4,
    zero_phase            = True,
)

mag_result = mag_filter.apply(values=rxmer_db)

print("RxMER series:")
print("  original shape:", mag_result.original_values.shape)
print("  filtered shape:", mag_result.filtered_values.shape)
```

In a typical PyPNM analysis pipeline, the `subcarrier_spacing_hz` and the
coefficient arrays would come from parsed PNM files or live SNMP/TFTP
measurements, and the filtered outputs would be used as inputs to your
plotting or higher-level diagnostics (for example, group-delay computation
or echo detection).
