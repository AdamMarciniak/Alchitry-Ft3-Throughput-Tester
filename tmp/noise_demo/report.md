# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 32 |
| Random noise | 5.476 counts (-51.46 dBFS RMS) |
| Repeatable component | 35.335 counts (-35.26 dBFS RMS) |
| Total AC | 35.757 counts (-35.16 dBFS RMS) |
| Peak | 332.0 counts (-15.80 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 482.445 (Gaussian = 3) |
| Effective bits from random noise | 7.754 |

## Findings

### MEDIUM: Repeatable energy is stronger than frame-to-frame random noise, consistent with transmit feedthrough, ringdown, or synchronous pickup.

Next test: Compare probe-in-air, probe-loaded, and transmit-voltage conditions; repeatable early energy that tracks voltage/loading is likely acoustic or HV feedthrough.

### MEDIUM: The random residual has heavy tails, indicating intermittent spikes or burst noise.

Next test: Capture more frames and trigger a bench scope on the affected time gate while monitoring rails and digital control lines.

## Strongest random-noise tones

No narrow line exceeded 6 dB prominence over its local floor.

## Localized regions

| Time | Equivalent depth | Classification | Excess |
|---:|---:|---|---:|
| 0.000–19.200 us | 0.374–1.810 cm | repeatable_coherent_artifact | 18.44 dB |
| 32.000–38.400 us | 2.768–3.246 cm | impulsive_or_bursty | 4.75 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
