# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 128 |
| Random noise | 6.243 counts (-50.32 dBFS RMS) |
| Repeatable component | 21.535 counts (-39.56 dBFS RMS) |
| Total AC | 22.422 counts (-39.21 dBFS RMS) |
| Peak | 347.0 counts (-15.42 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 83.440 (Gaussian = 3) |
| Effective bits from random noise | 7.565 |

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

No narrow line exceeded 6 dB prominence over its local floor.

## Localized regions

| Time | Equivalent depth | Classification | Excess |
|---:|---:|---|---:|
| 0.000–19.200 us | 0.374–1.810 cm | repeatable_coherent_artifact | 21.05 dB |
| 64.000–89.600 us | 5.161–7.076 cm | elevated_random_noise | 8.66 dB |
| 96.000–102.400 us | 7.555–8.034 cm | impulsive_or_bursty | 3.94 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
