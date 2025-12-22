# Phase‑Slope Echo Detection: Theory and Insights

This guide delves into the theory of phase‑slope echo detection, examines how front‑end AGC and in‑band LTE signals affect group‑delay estimates, and presents a multi‑resolution scanning strategy to pinpoint disturbances.


## 1. Fundamental Principle

A simple two‑path channel (direct path + reflection) has the frequency response:

$$
H(f) = H_0 + H_1\,e^{-j2\pi f\,\tau_{rt}},
$$

where:

* $H_0$ is the direct‑path complex gain.
* $H_1$ is the echo path gain.
* $\tau_{rt}$ is the **round‑trip** delay of the echo.

Taking the phase and unwrapping across subcarriers gives:

$$
\varphi(f) = \arg H(f) \approx -2\pi f\,\tau_{rt} + \text{constant}.
$$

A linear fit $\varphi(f) \approx a f + b$ yields slope:

$$
a = \frac{d\varphi}{df} \approx -2\pi\,\tau_{rt},
\quad
\tau_{rt} = -\frac{a}{2\pi}.
$$

Thus, the **one‑way** delay is

$$
\tau = \frac{|\tau_{rt}|}{2},
$$

and the distance to the reflector:

$$
d = v\,\tau,
$$

with propagation velocity $v = c_0 \times \mathrm{prop\_speed\_frac}$.


## 2. Effects of AGC and In‑Band Signals

* **AGC dynamics**: The Automatic Gain Control adjusts amplifier gain based on total in‑band power. A strong LTE signal (e.g., 40 MHz) within a wider OFDM band (e.g., 100 MHz) shifts the AGC operating point.

* **Phase ripple**: Gain adjustments introduce frequency‑dependent phase shifts (group‑delay ripple) that corrupt linear phase assumptions.

* **Impact**: The measured slope reflects both echo delay and AGC/equalizer transients until front‑end circuits re‑settle.


## 3. Group‑Delay Flatness Metric

Let $\tau_k$ be the one‑way delay estimated at subcarrier $f_k$. Define:

1. **Global statistics**:

   $$
   \mu = \frac{1}{K}\sum_{k=1}^K \tau_k,
   \quad
   \sigma_{\mathrm{tot}} = \sqrt{\frac{1}{K-1}\sum_{k=1}^K (\tau_k - \mu)^2}.
   $$

2. **Local variability**: Divide the occupied channel bandwidth $B$ into $N_b$ bins (e.g., 1 MHz each). For bin $j$ with indices $\mathcal{K}_j$:

   $$
   \mu_j = \frac{1}{|\mathcal{K}_j|}\sum_{k\in\mathcal{K}_j} \tau_k,
   \quad
   \sigma_j = \sqrt{\frac{1}{|\mathcal{K}_j|-1}\sum_{k\in\mathcal{K}_j}(\tau_k - \mu_j)^2}.
   $$

3. **Anomaly metric**:

   $$
   \Delta\sigma_j = |\sigma_j - \sigma_{\mathrm{tot}}|.
   $$

Flag bin $j$ as disturbed if $\Delta\sigma_j > T$, where $T$ is a threshold based on baseline ripple levels.


## 4. Multi‑Resolution Scanning Strategy

1. **Coarse scan**: Compute $\Delta\sigma_j$ over large bins (e.g., 1 MHz).
2. **Bin selection**: Mark bins where $\Delta\sigma_j > T$.
3. **Refinement**: Subdivide flagged bins into finer bins (e.g., 500 kHz, then 100 kHz), recompute metrics, and localize disturbances.
4. **Repeat**: Continue until desired frequency resolution is achieved.

This hierarchical method focuses computation on suspect regions, optimizing performance.


## 5. Practical Considerations

* **Phase unwrapping**: Use robust algorithms (e.g., `numpy.unwrap`) to avoid 2π jumps.
* **Threshold tuning**: Set $T$ as a multiple (e.g., 3×) of baseline $\sigma_{\mathrm{tot}}$.
* **AGC/EQ modeling**: Consider digital filter group‑delay and DC‑offset compensation.
* **Extensions**: Combine with PSD analysis or pilot-correlation to reduce false positives.


## 6. References

1. Delay Estimation via Phase Slope, DSPRelated.com
2. Multipath Channel Models and Rake Receivers, WirelessPi


> **Tip:** Always verify AGC settling time and remove large in-band interferers before echo analysis.
