# OFDM Echo Detector and Coax Cable Propagation Guide

This guide explains the `OFDMEchoDetector` class, which performs FFT/IFFT-based echo detection on OFDM channel estimates, and provides typical propagation delay values for common coaxial drop cables.


## 1. Class Overview

The `OFDMEchoDetector` class:

* Accepts a 1-D array of complex OFDM channel estimates (`H[k]`).
* Computes the time-domain impulse response via inverse FFT.
* Identifies the direct path and the first significant echo reflection.
* Calculates the echo delay and converts it into distance using a configurable propagation speed factor.

**Key Methods**

* `compute_time_response()`
  Computes:

  * `time_axis`: $t[n]$ values in seconds.
  * `time_response`: impulse response $h[n]$.

* `detect_reflection(threshold_frac, min_separation)`
  Detects peaks in `time_response`:

  * Returns a `dict` containing indices, times, one-way delay, and distance.

* `compute_freq_response(time_data)`
  Optionally applies FFT to reconstruct frequency response from time-domain data.


## 2. Mathematical Foundations

1. **Inverse FFT**

   $$
   h[n] = \frac{1}{N} \sum_{k=0}^{N-1} H[k] \,e^{j2\pi k n / N}
   $$

2. **Time Axis**

   $$
   t[n] = \frac{n}{F_s}, \quad n=0,1,\ldots,N-1
   $$

3. **Reflection Delay**

   $$
   \Delta t = t_{\mathrm{echo}} - t_{\mathrm{direct}}
   $$

4. **One-Way Distance**

   $$
   d = \frac{c_0 \times \mathrm{prop\_speed\_frac} \times \Delta t}{2}
   $$

   * $c_0$: speed of light in vacuum.
   * `prop_speed_frac`: velocity factor relative to $c_0$.


## 3. Typical Usage

1. **Instantiate detector**

   ```python
   detector = OFDMEchoDetector(
       H,                 # Complex channel estimates
       sample_rate=Fs,    # Sampling rate in Hz
       prop_speed_frac=0.87  # Velocity factor
   )
   ```

2. **Compute time-domain response**

   ```python
   t, h = detector.compute_time_response()
   ```

3. **Detect echo reflection**

   ```python
   result = detector.detect_reflection(
       threshold_frac=0.2,  # Fraction of peak direct path magnitude
       min_separation=1     # Minimum sample separation between direct and echo
   )
   print(result)
   ```


## 4. Coax Cable Propagation Delays

| Cable Type              | Velocity Factor ($% of \(c_0$)) | Delay (ns/ft) | Delay (ns/m) |
| ----------------------- | ------------------------------- | ------------- | ------------ |
| **RG-59A/U PE**         | 65.9                            | 1.52          | 4.99         |
| **RG-6/U Quad Shield**  | 84.5                            | 1.18          | 3.87         |
| **RG-11/U Quad Shield** | 86.0                            | 1.16          | 3.81         |

* **Delay (ns/ft)** = $1/\mathrm{velocity\_factor}$.
* **Delay (ns/m)** = Delay (ns/ft) × 3.28084.


## 5. References

* **RG-59A/U PE** velocity and delay (CableLabs)
* **RG-6/U Quad Shield** velocity factors (Manufacturer datasheets)
* **RG-11/U** NVP and delay (Technical specifications)


> **Tip:** Use the `compute_freq_response` method to verify the FFT/IFFT round-trip, ensuring no windowing artifacts affect echo detection.
