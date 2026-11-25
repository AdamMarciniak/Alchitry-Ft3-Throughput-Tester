# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 128 |
| Random noise | 3.958 counts (-54.28 dBFS RMS) |
| Repeatable component | 46.058 counts (-32.96 dBFS RMS) |
| Total AC | 46.228 counts (-32.93 dBFS RMS) |
| Peak | 1201.0 counts (-4.64 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 1222.158 (Gaussian = 3) |
| Effective bits from random noise | 8.223 |

## Findings

### MEDIUM: Repeatable energy is stronger than frame-to-frame random noise, consistent with transmit feedthrough, ringdown, or synchronous pickup.

Next test: Compare probe-in-air, probe-loaded, and transmit-voltage conditions; repeatable early energy that tracks voltage/loading is likely acoustic or HV feedthrough.

### MEDIUM: One or more narrow spectral lines rise clearly above the local noise floor; the component label shows whether each line repeats with the shot.

Next test: Correlate the listed frequencies and harmonics with switching regulators, clocks, USB activity, and the transmit centre frequency; vary transmit amplitude to distinguish acoustic/ringdown lines from electrical pickup.

### MEDIUM: Noise is not stationary across the receive window; one or more time/depth regions are materially worse.

Next test: Use the reported time/depth gates to relate each rise to ringdown, TGC changes, supply settling, or a fixed-delay digital event.

### MEDIUM: The random residual has heavy tails, indicating intermittent spikes or burst noise.

Next test: Capture more frames and trigger a bench scope on the affected time gate while monitoring rails and digital control lines.

## Strongest random-noise tones

| Frequency | Prominence | Estimated RMS |
|---:|---:|---:|
| 0.009766 MHz | 8.02 dB | -88.00 dBFS |

## Localized regions

| Time | Equivalent depth | Classification | Excess |
|---:|---:|---|---:|
| 0.000–12.800 us | 0.374–1.331 cm | impulsive_or_bursty | 48.66 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
