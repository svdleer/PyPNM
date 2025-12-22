# EchoDetector — FFT/IFFT-based Echo Analysis (Docsis OFDM)

## Overview

**EchoDetector** converts frequency-domain channel estimates (H[k]) into a time-domain impulse response (h[n]) via IFFT, then locates the **direct path** and subsequent **echo peaks**. Echo timing is mapped to **one-way distance** using a cable-dependent propagation speed (v = c_0 \cdot \text{VF}).

* **Supports**: single snapshot or multiple snapshots (coherent average), complex arrays or ((\mathrm{Re},\mathrm{Im})) pairs.
* **OFDM context**: sample rate (f_s = N \cdot \Delta f) for (N) subcarriers and spacing (\Delta f) (25/50 kHz typical in DOCSIS 3.1/4.0).
* **Distance model**: one-way (d = \dfrac{v \cdot \Delta t}{2}), where (\Delta t) is echo delay relative to direct path.

## Inputs & Assumptions

* **Frequency data** (`freq_data`):

  * Shape: ((N,)) complex, ((M,N)) complex, ((N,2)) re/imag pairs, or ((M,N,2)) re/imag pairs.
  * If multiple snapshots (M>1), a **coherent average** across snapshots is used for detection.
* **Subcarrier spacing** (\Delta f) (Hz): commonly 25 kHz or 50 kHz.
* **IFFT size** (n_{\text{fft}}): optional zero-padding (n_{\text{fft}} \ge N) to improve **time resolution** of peak indices; the time step remains (\Delta t = 1/f_s).
* **Cable type / velocity factor (VF)**: picks (v = c_0\cdot\text{VF}) (RG6/RG11: ~0.87, RG59: ~0.82 by default).

## Core Math

### Frequency → Time

Given (H[k]) for (k=0,\dots,N-1):
[
h[n] = \text{IFFT}{H[k]}*{n=0}^{n*{\text{fft}}-1}, \quad
t[n] = \frac{n}{f_s}, \quad f_s = N\cdot\Delta f .
]

Magnitude:
[
|h[n]| = \sqrt{ \Re{h[n]}^2 + \Im{h[n]}^2 }.
]

### Direct Path & First Echo

1. **Direct path** index (i_0 = \arg\max_n |h[n]|), amplitude (A_0 = |h[i_0]|).
2. **Threshold** (\tau = \text{threshold_frac} \cdot A_0).
3. **Guard region**: skip indices (i \le i_0 + \text{guard_bins}).
4. **Echo**: first (i_e>i_0) with (|h[i_e]|\ge\tau) (optionally capped by `max_delay_s`).

Delay & distance:
[
\Delta t = t[i_e] - t[i_0], \qquad d = \frac{v \cdot \Delta t}{2}, \quad v=c_0\cdot\text{VF}.
]

### Multiple Echoes

* Find **local maxima** in the search window with (|h[i]|\ge\tau).
* Sort by magnitude (desc), then **enforce min spacing** in time (`min_separation_s`) before selecting up to `max_peaks`.

## Tuning Knobs

* `threshold_frac` (0-1): sensitivity; larger ⇒ fewer echoes.
* `guard_bins` (≥0): avoids main-lobe skirt around the direct path.
* `max_delay_s` (optional): caps search window (controls false positives far out).
* `min_separation_s` (multi): enforces spacing between returned echoes.
* `max_peaks` (multi): upper bound on echoes reported.
* `n_fft` (≥N): zero-padding improves bin granularity for peak location.

## Returned Models

### EchoDatasetInfo

| Field                 | Type  | Description                  |
| --------------------- | ----- | ---------------------------- |
| subcarriers           | int   | Number of frequency bins (N) |
| snapshots             | int   | Number of snapshots (M)      |
| subcarrier_spacing_hz | float | (\Delta f) in Hz             |
| sample_rate_hz        | float | (f_s = N\cdot\Delta f)       |

### EchoPath

| Field       | Type  | Description           |   |           |
| ----------- | ----- | --------------------- | - | --------- |
| bin_index   | int   | Peak index in (       | h | )         |
| time_s      | float | Peak time (t)         |   |           |
| amplitude   | float | (                     | h | ) at peak |
| distance_m  | float | One-way distance (m)  |   |           |
| distance_ft | float | One-way distance (ft) |   |           |

### EchoReflection (first-echo)

| Field                 | Type         | Description             |   |        |   |        |
| --------------------- | ------------ | ----------------------- | - | ------ | - | ------ |
| direct_index          | int          | Direct-path index       |   |        |   |        |
| echo_index            | int          | Echo index              |   |        |   |        |
| time_direct_s         | float        | Direct time (t[i_0])    |   |        |   |        |
| time_echo_s           | float        | Echo time (t[i_e])      |   |        |   |        |
| reflection_delay_s    | float        | (\Delta t)              |   |        |   |        |
| reflection_distance_m | float        | One-way distance (m)    |   |        |   |        |
| amp_direct            | float        | (                       | h | [i_0]) |   |        |
| amp_echo              | float        | (                       | h | [i_e]) |   |        |
| amp_ratio             | float        | (                       | h | [i_e]/ | h | [i_0]) |
| threshold_frac        | float        | Threshold fraction used |   |        |   |        |
| guard_bins            | int          | Guard bins used         |   |        |   |        |
| max_delay_s           | float | None | Optional search window  |   |        |   |        |

### TimeResponse (optional iframe for plotting)

| Field         | Type                | Description                           |
| ------------- | ------------------- | ------------------------------------- |
| n_fft         | int                 | IFFT length used                      |
| time_axis_s   | list[float]         | (t[n]=n/f_s), length (n_{\text{fft}}) |
| time_response | list[(float,float)] | (h[n]) as ((\Re,\Im)) pairs           |

### EchoDetectorReport (multi-echo)

| Field            | Type                | Description                |
| ---------------- | ------------------- | -------------------------- |
| channel_id       | ChannelId           | OFDM downstream channel ID |
| dataset          | EchoDatasetInfo     | Shape & sampling meta      |
| cable_type       | "RG6", "RG59", "RG11" | Cable used for VF          |
| velocity_factor  | float               | VF actually used           |
| prop_speed_mps   | float               | (v=c_0\cdot\text{VF})      |
| direct_path      | EchoPath            | Direct-path sample         |
| echoes           | list[EchoPath]      | Selected echo peaks        |
| threshold_frac   | float               | Threshold used             |
| guard_bins       | int                 | Guard bins used            |
| min_separation_s | float               | Min echo spacing (s)       |
| max_delay_s      | float | None        | Max search window          |
| max_peaks        | int                 | Max echoes returned        |
| time_response    | TimeResponse | None | Optional plotting block    |


## Typical Workflow

1. **Construct** the detector with (H) and (\Delta f):

   * Optional: set (n_{\text{fft}}) and `cable_type` (or custom VF).
2. **First echo**:

   * Call `first_echo(threshold_frac, guard_bins, max_delay_s?)` → **EchoReflection**.
3. **Multi-echo**:

   * Call `multi_echo(threshold_frac, guard_bins, min_separation_s, max_delay_s?, max_peaks, include_time_response)` → **EchoDetectorReport**.
4. **Plotting**:

   * Use `time_response` block if returned, or reconstruct via (h=\text{IFFT}(H)).


## Practical Notes

* **Resolution trade-offs**:

  * Time grid is fixed by (f_s=N\cdot\Delta f).
  * Zero-padding refines **bin placement** but not the fundamental (\Delta t).
* **Leakage & windowing**:

  * If leakage is strong, consider pre-conditioning (H[k]) or smoothing; `guard_bins` mitigates main-lobe bleed-through.
* **Robustness**:

  * Choose `threshold_frac` to balance sensitivity vs. false positives.
  * Use `max_delay_s` to limit distant artifacts.
  * Increase `min_separation_s` when echoes cluster.

## Example (conceptual)

```python
# H: (N,) complex or (N,2) pairs; df=25e3 or 50e3
det = EchoDetector(H, subcarrier_spacing_hz=50_000.0, n_fft=2048, cable_type="RG6")

# First echo
ref = det.first_echo(threshold_frac=0.2, guard_bins=2)
print(ref.reflection_distance_m, ref.amp_ratio)

# Multiple echoes
rep = det.multi_echo(threshold_frac=0.2, guard_bins=1,
                     min_separation_s=1e-6, max_peaks=5,
                     include_time_response=True, channel_id=42)
for e in rep.echoes:
    print(e.time_s, e.distance_m)
```

## Units & Conventions

* (c_0 = 299,792,458\ \mathrm{m/s})
* (\text{VF} \in (0,1)), defaults (can be overridden): RG6/RG11 ~ 0.87, RG59 ~ 0.82
* **Distances** are **one-way**, relative to the modem input.
* **Time axis** always **starts at 0** with step (1/f_s).

## Limitations

* Assumes **single dominant direct path**; deep fades at the true direct path can bias detection.
* Strong frequency-selective channels may require **pre-equalization or smoothing** before IFFT.
* Echoes closer than the effective time resolution or within `guard_bins` cannot be separated.
