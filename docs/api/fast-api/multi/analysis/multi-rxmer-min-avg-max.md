# Multi-Capture RxMER - Min / Average / Max Math

Foundations For Temporal Aggregation Of Per-Subcarrier RxMER Measurements.

## Overview

This note defines the mathematical operations used by the **Multi-Capture RxMER Min/Avg/Max** analysis.

The goal is to combine multiple downstream OFDM RxMER captures, taken at different times, into a small set of
summary curves that describe, per subcarrier:

- The **minimum** observed RxMER over time
- The **arithmetic mean** (time-average) RxMER
- The **maximum** observed RxMER over time

These statistics are computed independently for each active subcarrier and can be plotted as three curves
over the same frequency or subcarrier index axis.

## Notation

Let:

- \(K \in \mathbb{N}\) be the number of RxMER captures.
- \(N \in \mathbb{N}\) be the number of active subcarriers in the downstream OFDM channel.
- \(k \in \{1, \dots, K\}\) index the **capture** (time dimension).
- \(n \in \{1, \dots, N\}\) index the **subcarrier**.

For each capture \(k\) and subcarrier \(n\), define

\[
R_{k,n} \in \mathbb{R}
\]

as the RxMER value, in dB, reported for subcarrier \(n\) in capture \(k\).

We can view the complete dataset as a real-valued matrix

\[
R \in \mathbb{R}^{K \times N}, \quad
R =
\begin{bmatrix}
R_{1,1} & \dots & R_{1,N} \\
\vdots  & \ddots & \vdots \\
R_{K,1} & \dots & R_{K,N}
\end{bmatrix}.
\]

Each **row** corresponds to a single RxMER capture, and each **column** corresponds to a given subcarrier.

## Per-Subcarrier Min / Average / Max

For a fixed subcarrier \(n\), the multi-capture time series is

\[
\{ R_{1,n}, R_{2,n}, \dots, R_{K,n} \}.
\]

From this 1D series in time, we define:

### Minimum RxMER

\[
R^{\min}_n = \min_{1 \le k \le K} \, R_{k,n}.
\]

This is the worst-case (lowest) RxMER observed over all captures for subcarrier \(n\).

### Average (Mean) RxMER

\[
R^{\text{avg}}_n
  = \frac{1}{K} \sum_{k=1}^{K} R_{k,n}.
\]

This is the arithmetic mean over captures for subcarrier \(n\), treating all captures equally.

### Maximum RxMER

\[
R^{\max}_n = \max_{1 \le k \le K} \, R_{k,n}.
\]

This is the best-case (highest) RxMER observed over all captures for subcarrier \(n\).

### Optional Range (Span)

Sometimes it is useful to quantify the temporal variation at each subcarrier using the **range**:

\[
\Delta R_n = R^{\max}_n - R^{\min}_n.
\]

A large \(\Delta R_n\) indicates that subcarrier \(n\) shows significant instability over time, even if
the average RxMER is acceptable.

## Vector Form

Define the three per-subcarrier vectors

\[
\mathbf{R}^{\min}
  = \left( R^{\min}_1, R^{\min}_2, \dots, R^{\min}_N \right),
\]

\[
\mathbf{R}^{\text{avg}}
  = \left( R^{\text{avg}}_1, R^{\text{avg}}_2, \dots, R^{\text{avg}}_N \right),
\]

\[
\mathbf{R}^{\max}
  = \left( R^{\max}_1, R^{\max}_2, \dots, R^{\max}_N \right).
\]

In matrix notation, the per-subcarrier mean vector \(\mathbf{R}^{\text{avg}}\) can be written as

\[
\mathbf{R}^{\text{avg}}
  = \frac{1}{K} \, \mathbf{1}_K^\top R,
\]

where \(\mathbf{1}_K \in \mathbb{R}^K\) is an all-ones column vector and the result is a \(1 \times N\) row
vector of per-subcarrier averages.

The min and max vectors are obtained by column-wise reduction:

\[
R^{\min}_n = \min_{k} R_{k,n}, \quad
R^{\max}_n = \max_{k} R_{k,n}
\quad \text{for } n = 1, \dots, N.
\]

## Optional Higher-Order Statistics

While the core analysis focuses on Min/Avg/Max, higher-order statistics can be derived per subcarrier:

### Per-Subcarrier Variance

\[
\sigma^2_n
  = \frac{1}{K} \sum_{k=1}^{K} \left( R_{k,n} - R^{\text{avg}}_n \right)^2.
\]

### Per-Subcarrier Standard Deviation

\[
\sigma_n = \sqrt{\sigma^2_n}.
\]

These metrics measure temporal dispersion of RxMER at each subcarrier and can highlight carriers that are
noise-sensitive or intermittently impacted by interference.

## Mapping To Modulation Capacity (Optional)

If you define a mapping

\[
f : \mathbb{R} \to \mathbb{R},
\]

that converts RxMER (in dB) to an effective metric such as **bits per symbol** or **Shannon capacity per subcarrier**, then you can apply the same Min/Avg/Max process in that transformed space.

For example, for a per-subcarrier function \(f(R_{k,n})\), define

\[
B_{k,n} = f(R_{k,n}),
\]

and compute

\[
B^{\min}_n = \min_k B_{k,n}, \quad
B^{\text{avg}}_n = \frac{1}{K} \sum_{k=1}^{K} B_{k,n}, \quad
B^{\max}_n = \max_k B_{k,n}.
\]

This preserves the same aggregation structure but on a modulation-oriented scale instead of the raw RxMER.

## Practical Interpretation

- \(\mathbf{R}^{\min}\) shows the **worst-case** RxMER profile experienced across all captures (worst day).

- \(\mathbf{R}^{\text{avg}\!}\) shows the **typical** RxMER profile (average day).

- \(\mathbf{R}^{\max}\) shows the **best-case** profile (best day).

- \(\Delta R_n\), \(\sigma_n\) identify carriers whose RxMER is unstable over time.

Plotting the three curves on the same axis (e.g., frequency or subcarrier index) provides an immediate
visual indication of both **spatial variation** (across frequency) and **temporal variation** (spread between
min and max) in the downstream OFDM RxMER. 
