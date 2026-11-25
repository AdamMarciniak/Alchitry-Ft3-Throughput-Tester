# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 128 |
| Random noise | 2.525 counts (-58.18 dBFS RMS) |
| Repeatable component | 41.642 counts (-33.84 dBFS RMS) |
| Total AC | 41.719 counts (-33.82 dBFS RMS) |
| Peak | 1194.0 counts (-4.69 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 2148.446 (Gaussian = 3) |
| Effective bits from random noise | 8.871 |

## Findings

### MEDIUM: Repeatable energy is stronger than frame-to-frame random noise, consistent with transmit feedthrough, ringdown, or synchronous pickup.

Next test: Compare probe-in-air, probe-loaded, and transmit-voltage conditions; repeatable early energy that tracks voltage/loading is likely acoustic or HV feedthrough.

### MEDIUM: Noise is not stationary across the receive window; one or more time/depth regions are materially worse.

Next test: Use the reported time/depth gates to relate each rise to ringdown, TGC changes, supply settling, or a fixed-delay digital event.

### MEDIUM: The random residual has heavy tails, indicating intermittent spikes or burst noise.

Next test: Capture more frames and trigger a bench scope on the affected time gate while monitoring rails and digital control lines.

## Strongest random-noise tones

| Frequency | Prominence | Estimated RMS |
|---:|---:|---:|
| 0.009766 MHz | 9.60 dB | -86.73 dBFS |

## Localized regions

| Time | Equivalent depth | Classification | Excess |
|---:|---:|---|---:|
| 0.000–51.200 us | 0.374–4.204 cm | impulsive_or_bursty | 47.56 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
