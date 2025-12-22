# Min-Avg-Max Complex Statistics Guide

This document describes a purely mathematical view of the Min-Avg-Max statistics computed from
per-subcarrier complex channel-estimation coefficients across multiple snapshots.

We assume a downstream OFDM channel with:

- \(K\) subcarriers (frequency bins)
- \(M\) snapshots (independent captures of the same channel)

All statistics are computed per subcarrier by aggregating across snapshots.

## 1. Complex Channel Matrix

Let the complex channel estimate for snapshot \(m\) and subcarrier \(k\) be

\[
H^{(m)}[k] \in \mathbb{C},
\quad
m = 0,\dots,M-1,
\quad
k = 0,\dots,K-1.
\]

We can write each coefficient in terms of its real and imaginary parts:

\[
H^{(m)}[k] = \Re\{H^{(m)}[k]\} + j\,\Im\{H^{(m)}[k]\},
\]

and define the real and imaginary matrices

\[
R_{m,k} = \Re\{H^{(m)}[k]\},
\qquad
I_{m,k} = \Im\{H^{(m)}[k]\},
\]

which form two real-valued arrays of size \(M \times K\).

## 2. Per-Subcarrier Real-Part Statistics

For each subcarrier \(k\), the minimum, average, and maximum of the real part across all
snapshots are defined as:

\[
\begin{aligned}
r_{\min}[k] &= \min_{0 \le m < M} R_{m,k}, \\
r_{\text{avg}}[k] &= \frac{1}{M} \sum_{m=0}^{M-1} R_{m,k}, \\
r_{\max}[k] &= \max_{0 \le m < M} R_{m,k}.
\end{aligned}
\]

The sequences

\[
\{r_{\min}[k]\}_{k=0}^{K-1},\quad
\{r_{\text{avg}}[k]\}_{k=0}^{K-1},\quad
\{r_{\max}[k]\}_{k=0}^{K-1}
\]

form the Min-Avg-Max real-part profiles across the OFDM band.

## 3. Per-Subcarrier Imaginary-Part Statistics

Similarly, for the imaginary component we define

\[
\begin{aligned}
i_{\min}[k] &= \min_{0 \le m < M} I_{m,k}, \\[4pt]
i_{\text{avg}}[k] &= \frac{1}{M} \sum_{m=0}^{M-1} I_{m,k}, \\[4pt]
i_{\max}[k] &= \max_{0 \le m < M} I_{m,k}.
\end{aligned}
\]

The sequences

\[
\{i_{\min}[k]\}_{k=0}^{K-1},\quad
\{i_{\text{avg}}[k]\}_{k=0}^{K-1},\quad
\{i_{\max}[k]\}_{k=0}^{K-1}
\]

are the Min-Avg-Max imaginary-part profiles.

These statistics characterize how the in-phase and quadrature components of the channel vary across
snapshots for each subcarrier.

## 4. Magnitude Statistics

### 4.1 Instantaneous Magnitude

For each snapshot and subcarrier, the instantaneous magnitude of the complex channel is

\[
A^{(m)}[k] = \left|H^{(m)}[k]\right|
           = \sqrt{\bigl(\Re\{H^{(m)}[k]\}\bigr)^2 + \bigl(\Im\{H^{(m)}[k]\}\bigr)^2}.
\]

This yields a real-valued magnitude matrix \(\{A^{(m)}[k]\}\) of size \(M \times K\).

### 4.2 Min and Max Magnitude Across Snapshots

For each subcarrier, the minimum and maximum magnitude observed across all snapshots are

\[
\begin{aligned}
a_{\min}[k] &= \min_{0 \le m < M} A^{(m)}[k], \\[4pt]
a_{\max}[k] &= \max_{0 \le m < M} A^{(m)}[k].
\end{aligned}
\]

These describe the envelope of how strong or weak the channel can become at each subcarrier.

### 4.3 Coherent Average Magnitude

Instead of averaging magnitudes directly, a coherent average is formed by first averaging the
complex channel across snapshots, then taking the magnitude:

1. Complex average per subcarrier:

\[
\overline{H}[k] = \frac{1}{M} \sum_{m=0}^{M-1} H^{(m)}[k].
\]

2. Magnitude of the averaged complex channel:

\[
a_{\text{avg}}[k] = \left|\overline{H}[k]\right|
                  = \left|\frac{1}{M} \sum_{m=0}^{M-1} H^{(m)}[k]\right|.
\]

This is not, in general, equal to the average of magnitudes:

\[
a_{\text{avg}}[k] \neq \frac{1}{M} \sum_{m=0}^{M-1} \left|H^{(m)}[k]\right|
\]

unless all \(H^{(m)}[k]\) share the same phase. The coherent average

\[
a_{\text{avg}}[k] = \left|\overline{H}[k]\right|
\]

naturally accounts for phase alignment and destructive/constructive interference, making it
consistent with other phase-sensitive analyses (for example, group delay or echo detection).

## 5. Summary of Per-Subcarrier Outputs

For each subcarrier \(k\), the Min-Avg-Max complex statistics provide:

- Real part: \(r_{\min}[k],\ r_{\text{avg}}[k],\ r_{\max}[k]\).
- Imaginary part: \(i_{\min}[k],\ i_{\text{avg}}[k],\ i_{\max}[k]\).
- Magnitude: \(a_{\min}[k],\ a_{\text{avg}}[k],\ a_{\max}[k]\).

Plotted versus subcarrier frequency \(f_k\), these profiles show:

- The range of channel variation across snapshots (min vs max),
- The typical coherent channel strength per subcarrier (average magnitude),
- And how the real and imaginary components evolve across the OFDM band.

This provides a compact but information-rich view of channel stability and variability suitable for
diagnostics, visualization, and downstream PNM analyses.

