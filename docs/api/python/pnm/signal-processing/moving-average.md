# Moving Average Smoothing for OFDM-Domain Diagnostics

This note describes the sliding-window moving average filter used in PyPNM. It is
a simple, robust smoother that operates on real-valued series such as RxMER per
subcarrier, magnitude traces, or any scalar diagnostic sequence. The focus here
is on the underlying math, how edges and non-finite values are handled, and a
minimal usage example at the end.

## 1. Discrete-Time Moving Average

Given a real-valued sequence

\[
x[k], \quad k = 0, 1, \dots, N-1,
\]

and a positive integer window length \(M\), the **moving average** at index
\(k\) is the average of the \(M\) samples under a sliding window. For a
centered window, this can be written as

\[
y[k] = \frac{1}{M} \sum_{m = -L}^{R} x[k - m],
\]

where \(M = L + R + 1\), and \(L\) and \(R\) are the number of samples to
the left and right of the center. In the implementation:

- \(M = \text{n\_points}\)
- \(L = \left\lfloor M / 2 \right\rfloor\)
- \(R = M - 1 - L\)

For an **odd** window (for example, \(M = 7\)), we get symmetric support
\(L = 3\), \(R = 3\). For an **even** window (for example, \(M = 6\)),
support is asymmetric: \(L = 3\), \(R = 2\). PyPNM uses this convention
internally to define how many samples are included on each side of the center.

### 1.1 Convolution View

The moving average can also be expressed as a discrete-time convolution:

\[
y[k] = (h * x)[k] = \sum_{m=0}^{M-1} h[m] \, x[k - m],
\]

where the kernel \(h[m]\) is a constant-length box:

\[
h[m] = \frac{1}{M}, \quad m = 0, 1, \dots, M-1.
\]

In the implementation, this kernel is stored as

\[
\text{kernel} = \left[\frac{1}{M}, \frac{1}{M}, \dots, \frac{1}{M}\right].
\]

The choice of where to center the kernel relative to \(k\) (and how to handle
edges) is captured by the edge-handling mode.

## 2. Edge Handling Modes

Near the boundaries of the sequence, the centered window would extend beyond
the available samples. PyPNM supports two behaviors that determine how windows
are interpreted at the edges.

### 2.1 Reflect Mode

In `mode="reflect"`, the sequence is extended by reflection before convolution.

If we denote the original finite-length sequence by \(x[k]\), a padded sequence
\(x_{\text{pad}}[k]\) is formed by reflecting the data around the boundaries.
Convolution is then performed in `"valid"` mode, so that each original index
\(k\) has a fully defined window of length \(M\). This yields an output
sequence of the same length as the input.

Conceptually, reflect padding enforces a symmetric behavior at the edges: the
window near the first or last sample sees mirrored neighbors instead of zeros
or truncated support.

This mode is a good default when you want a centered, length-preserving smoother
with reasonably natural behavior at boundaries.

### 2.2 Same Mode

In `mode="same"`, the kernel is convolved directly with the input using NumPy's
`mode="same"` semantics:

\[
y[k] = (h * x)[k], \quad k = 0, 1, \dots, N-1.
\]

Here, the window near the boundaries is effectively truncated (partial overlap).
The result still has the same length as the input, but the contribution from
neighbors is reduced near the edges. This behavior tends to emphasize the
central region of the series and can be useful when you explicitly want
NumPy-style `"same"` convolution semantics.

## 3. Handling NaN and Infinite Values

Real-world diagnostic series may contain non-finite values such as NaN, \(+\infty\),
or \(-\infty\). PyPNM's moving average filter handles these robustly by using
a **masking** strategy:

1. Build a validity mask

   \[
   m[k] =
   \begin{cases}
   1, & \text{if } x[k] \text{ is finite},\\
   0, & \text{otherwise.}
   \end{cases}
   \]

2. Replace non-finite values with zero in a working array

   \[
   x_{\text{clean}}[k] =
   \begin{cases}
   x[k], & \text{if } x[k] \text{ is finite},\\
   0, & \text{otherwise.}
   \end{cases}
   \]

3. Convolve both arrays with the same averaging kernel:

   - Numerator: \(n[k] = (h * x_{\text{clean}})[k]\)
   - Denominator: \(d[k] = (h * m)[k]\)

4. Compute the masked average as

   \[
   y[k] =
   \begin{cases}
   \dfrac{n[k]}{d[k]}, & \text{if } d[k] > 0,\\
   0, & \text{if no finite samples fall under the window.}
   \end{cases}
   \]

This guarantees that non-finite values do not pollute the average, and that
windows containing only non-finite samples produce a deterministic result
(0.0 in this implementation).

## 4. Length Preservation and Output

Regardless of the mode:

- The **output length** is always equal to the input length.
- The filter maintains the overall scale of the signal, assuming a reasonable
  number of finite samples under each window.
- For smooth signals with small noise, increasing the window length reduces
  variance at the cost of reduced resolution for narrow features (for example,
  sharp notches or very localized events).

This trade-off mirrors the behavior of other low-pass smoothing methods, such
as Butterworth filters, but the moving average is simpler and does not introduce
IIR phase characteristics.

## 5. Use in OFDM and PNM Contexts

The moving average filter is generic, but in OFDM-centric diagnostics you can
interpret the index \(k\) in several ways:

- **Subcarrier index**: smoothing RxMER, SNR, or magnitude across frequency.
- **Snapshot index**: smoothing a time sequence of per-channel measurements.
- **Bin index**: smoothing histogram or other binned statistics.

Unlike the Butterworth filter, the moving average does not require an explicit
sample rate or cutoff frequency; you simply choose the number of points \(M\)
in the window. A few practical guidelines:

- Small window (for example, 3-5 points): light smoothing, preserves detail.
- Medium window (for example, 7-15 points): moderate smoothing, good for noisy
  traces with mild structure.
- Large window (for example, 31+ points): strong smoothing, may blur narrow
  features but highlight long-scale trends.

`mode="reflect"` is usually the most convenient starting point for PNM plot
smoothing, because it keeps the filter centered and mitigates edge artifacts.

## 6. Minimal Usage Example

Below is a minimal example using the `MovingAverage` helper to smooth a noisy
sequence. In a real PyPNM workflow, the `values` array would come from a parsed
PNM model (for example, RxMER per subcarrier), and the smoothed output would
feed plotting or higher-level analysis.

```python
import numpy as np

from pypnm.lib.signal_processing.moving_average import MovingAverage

# Synthetic noisy series (e.g., RxMER per subcarrier)
n = 256
k = np.arange(n, dtype=float)
signal = 40.0 + 2.0 * np.sin(2.0 * np.pi * k / 64.0)  # slow trend
noise  = 1.0 * np.random.randn(n)                     # additive noise
values = (signal + noise).tolist()

# Create a moving average filter with a 9-point window
ma = MovingAverage(n_points=9, mode="reflect")

smoothed = ma.apply(values)

print("Original length:", len(values))
print("Smoothed length:", len(smoothed))
print("First 5 samples (original):", values[:5])
print("First 5 samples (smoothed):", smoothed[:5])
```

In practice, you would pass `smoothed` into your plotting layer (for example,
PyPNM's Matplotlib manager) to overlay a clean trend line on top of raw
measurement data.
