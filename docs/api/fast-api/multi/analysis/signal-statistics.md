# Signal Statistics Guide

This guide describes the key time-domain statistics computed by the `SignalStatistics` class, explaining each metric’s meaning and practical applications in signal processing.

## Overview

Time-domain statistics summarize raw signal samples using simple formulas. They provide insights into signal characteristics such as:

* **Central tendency** (mean, median)
* **Dispersion** (variance, standard deviation, MAD)
* **Shape** (skewness, kurtosis)
* **Extremes** (peak-to-peak, crest factor)
* **Frequency proxies** (zero-crossing rate)

These metrics are widely used for anomaly detection, quality assessment, feature extraction for machine learning, and diagnostic monitoring.


## Metrics and Definitions

Given a sequence of $N$ samples $x_1, x_2, \dots, x_N$ with mean $\mu$:

| Statistic                         | Definition                                                                    | Interpretation / Use                                          |
| --------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------- |
| **Mean**                          | $\displaystyle \mu = \frac{1}{N}\sum_{i=1}^N x_i$                             | DC offset or bias; used for baseline correction               |
| **Median**                        | Middle value of sorted $\{x_i\}$                                              | Robust central tendency; insensitive to outliers              |
| **Variance**                      | $\displaystyle \sigma^2 = \frac{1}{N}\sum_{i=1}^N (x_i - \mu)^2$              | Dispersion measure; basis for power and energy analyses       |
| **Standard Deviation** ($\sigma$) | $\displaystyle \sigma = \sqrt{\sigma^2}$                                      | Spread around mean; indicates noise level                     |
| **Mean Absolute Deviation**       | $\displaystyle \mathrm{MAD} = \frac{1}{N}\sum_{i=1}^N \lvert x_i - \mu\rvert$ | Robust dispersion; less sensitive to outliers                 |
| **Power**                         | $\displaystyle P = \frac{1}{N}\sum_{i=1}^N x_i^2$                             | Energy per sample; key for signal strength and SNR            |
| **Peak-to-Peak**                  | $\displaystyle \max_i x_i - \min_i x_i$                                       | Dynamic range; checks for clipping or saturation              |
| **Crest Factor**                  | $\displaystyle \frac{\max_i \lvert x_i\rvert}{\sqrt{P}}$                      | Peak prominence relative to average power; important in audio |
| **Skewness**                      | $\displaystyle \frac{1}{N\sigma^3}\sum_{i=1}^N (x_i - \mu)^3$                 | Distribution asymmetry; indicates DC shifts or bursts         |
| **Kurtosis**                      | $\displaystyle \frac{1}{N\sigma^4}\sum_{i=1}^N (x_i - \mu)^4$                 | Tail heaviness relative to Gaussian; spots impulses/spikes    |
| **Zero-Crossing Rate (ZCR)**      | $\displaystyle \frac{1}{N-1}\sum_{i=1}^{N-1} \mathbf{1}[x_i x_{i+1}<0]$       | Proxy for frequency content; higher ZCR → higher frequencies  |
| **Zero Crossings**                | Total count of sign changes: $\sum_{i=1}^{N-1} \mathbf{1}[x_i x_{i+1}<0]$     | Basic oscillation count; complements ZCR                      |


## Practical Applications

1. **Anomaly Detection**
   Sudden spikes in kurtosis or a high crest factor can indicate faults or transient events.

2. **Quality Assessment**
   Noise level is quantified by $\sigma$ and MAD; peak-to-peak highlights clipping or saturation.

3. **Feature Extraction**
   These metrics serve as features in machine learning models for classification, regression, or clustering.

4. **Monitoring & Diagnostics**
   Tracking mean and power over time helps detect drift, component aging, or environmental changes.


> **Tip:** Always normalize or detrend your signal (remove its mean $\mu$) before computing higher-order moments (skewness, kurtosis) to avoid bias from DC offsets.
