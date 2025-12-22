# Group Delay Calculator Guide

This document describes the mathematical basis for computing **group delay** from per-subcarrier complex channel estimates, including coherent averaging across multiple snapshots and robust statistics such as the median group delay.

## 1. Group Delay: Continuous Definition

For a complex frequency response \(H(f)\), the **group delay** is defined as the negative derivative of the phase with respect to angular frequency \(\omega\):

\[
\tau_g(f) = -\frac{d}{d\omega} \arg\bigl(H(f)\bigr),
\]

where

\[
\omega = 2\pi f,
\]
and \(\arg(H(f))\) is the phase of \(H(f)\) in radians.

Using the chain rule,

\[
\frac{d}{d\omega} = \frac{1}{2\pi} \frac{d}{df},
\]

so the group delay can also be written as

\[
\tau_g(f) = -\frac{1}{2\pi}\frac{d}{df}\arg\bigl(H(f)\bigr).
\]

Thus, group delay measures how rapidly the phase of the channel response changes with frequency.

## 2. Discrete Approximation on Subcarriers

Consider a set of \(K\) subcarriers at frequencies \(f_k\) with corresponding complex responses \(H[k]\). The **unwrapped** phase at each subcarrier is

\[
\phi_k = \mathrm{unwrap}\bigl(\angle H[k]\bigr),
\]

where \(\angle H[k]\) is the principal value of the phase and \(\mathrm{unwrap}(\cdot)\) removes \(2\pi\) discontinuities.

A discrete approximation of the group delay at each subcarrier is obtained by finite differences of the phase with respect to frequency:

- **Forward difference** at the lower edge \(k = 0\):

  \[
  \tau_g[0] = -\frac{\phi_1 - \phi_0}{2\pi(f_1 - f_0)}.
  \]

- **Central difference** for interior subcarriers \(1 \le k \le K-2\):

  \[
  \tau_g[k] = -\frac{\phi_{k+1} - \phi_{k-1}}{2\pi(f_{k+1} - f_{k-1})}.
  \]

- **Backward difference** at the upper edge \(k = K-1\):

  \[
  \tau_g[K-1] = -\frac{\phi_{K-1} - \phi_{K-2}}{2\pi(f_{K-1} - f_{K-2})}.
  \]

These formulas assume that the frequency samples \(f_k\) are known and that no two adjacent frequencies are identical, so that the denominators are non-zero.

## 3. Multi-Snapshot Coherent Averaging

Often, multiple snapshots of the channel are available. Let \(H^{(m)}[k]\) denote the complex channel estimate for snapshot \(m \in \{0,\dots,M-1\}\) and subcarrier \(k \in \{0,\dots,K-1\}\).

### 3.1 Coherent Average Channel

A **coherent complex average** across snapshots is formed as

\[
H_{\text{avg}}[k] = \frac{1}{M} \sum_{m=0}^{M-1} H^{(m)}[k],
\]

which averages both real and imaginary parts:

\[
H_{\text{avg}}[k] = \frac{1}{M} \sum_{m=0}^{M-1} 
\Bigl( \Re\{H^{(m)}[k]\} + j\,\Im\{H^{(m)}[k]\} \Bigr).
\]

This suppresses uncorrelated noise while preserving the underlying channel structure (e.g., echoes, dispersion).

The unwrapped phase of the averaged channel is

\[
\phi_{\text{avg}}[k] = \mathrm{unwrap}\bigl(\angle H_{\text{avg}}[k]\bigr),
\]

and the corresponding **full group delay** on the averaged channel is obtained by applying the finite-difference formulas from Section 2 to \(\phi_{\text{avg}}[k]\):

\[
\tau_{g,\text{full}}[k] \approx -\frac{1}{2\pi}\frac{\Delta \phi_{\text{avg}}}{\Delta f}.
\]

### 3.2 Per-Snapshot Group Delay

Alternatively, the group delay can be computed **separately for each snapshot**. For each \(m\), define

\[
\phi^{(m)}_k = \mathrm{unwrap}\bigl(\angle H^{(m)}[k]\bigr),
\]

and compute

\[
\tau_g^{(m)}[k] \approx -\frac{1}{2\pi}\frac{\Delta \phi^{(m)}}{\Delta f},
\]

again using forward / central / backward finite differences over \(k\) for each snapshot independently. This produces a group delay matrix

\[
\tau_g^{(m)}[k], \quad m = 0,\dots,M-1,\ \ k = 0,\dots,K-1,
\]

which captures the variation of group delay over time (snapshot index).

### 3.3 Median Group Delay Across Snapshots

To obtain a **robust statistic** that is less sensitive to outliers, one can take the median of per-snapshot group delays across the snapshot dimension:

\[
\tau_{g,\mathrm{med}}[k] = \mathrm{median}\bigl\{\tau_g^{(0)}[k],\tau_g^{(1)}[k],\dots,\tau_g^{(M-1)}[k]\bigr\}.
\]

This yields a single group delay curve \(\tau_{g,\mathrm{med}}[k]\) across subcarriers that is robust against occasional corrupted snapshots or impulsive noise.

## 4. Requirements on the Frequency Axis

The frequency samples \(\{f_k\}_{k=0}^{K-1}\) used in the finite-difference approximations must satisfy:

1. **One-dimensionality**:
   \[
   f_k \in \mathbb{R}, \quad k = 0,\dots,K-1.
   \]

2. **At least two points**:
   \[
   K \ge 2.
   \]

3. **Non-duplicate spacing**:
   \[
   f_{k+1} \neq f_k \quad \text{for all } k,
   \]
   so that the denominators in the finite differences are non-zero.

4. **Monotonicity** (typically):
   \[
   f_{k+1} > f_k \quad \text{for all } k,
   \]
   which ensures a well-behaved mapping from subcarrier index to frequency.

In many OFDM systems, \(f_k\) is uniformly spaced:

\[
f_k = f_0 + k\,\Delta f,
\]

where \(f_0\) is the starting frequency and \(\Delta f\) is the subcarrier spacing. In this case, the denominators simplify to constant steps such as \(2\pi\Delta f\) or \(2\pi(2\Delta f)\), but the general finite-difference formulas remain valid.

## 5. Physical Interpretation

Group delay \(\tau_g(f)\) is closely related to the **propagation time** of signals through the channel. Large deviations or sharp variations in \(\tau_g(f)\) can indicate:

- Dispersive behavior of the medium.
- Echoes or multipath reflections.
- Distortions caused by filters, amplifiers, or other network elements.

For a dominant echo at delay \(\tau_{\text{echo}}\), characteristic structure can appear in the group delay and phase responses. With knowledge of the propagation speed \(v\) in the medium (e.g., coax velocity factor), the delay can be translated into an approximate path length

\[
d \approx v \,\tau_{\text{echo}},
\]

providing insight into where in the plant an echo or reflection might originate.

Coherent averaging and median aggregation across snapshots, as described above, help stabilize \(\tau_g(f)\) against noise, making it a more reliable feature for diagnostics and echo detection.
