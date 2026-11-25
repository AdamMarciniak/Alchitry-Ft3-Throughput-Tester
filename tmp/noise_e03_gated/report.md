# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

Assessment gate starts at **3.002 cm** (37.250 µs into the captured waveform). The earlier limiter saturation/ringdown interval is retained as context but is not graded.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 128 |
| Random noise | 0.769 counts (-68.51 dBFS RMS) |
| Repeatable component | 0.687 counts (-69.49 dBFS RMS) |
| Total AC | 1.031 counts (-65.96 dBFS RMS) |
| Peak | 10.0 counts (-46.23 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 2.983 (Gaussian = 3) |
| Effective bits from random noise | 10.587 |

## Excluded near-field context

The ignored interval peaks at 1194.0 counts (-4.69 dBFS) and has -27.50 dBFS of repeatable energy. These values do not affect the overall assessment.

## Findings

### MEDIUM: One or more narrow spectral lines rise clearly above the local noise floor; the component label shows whether each line repeats with the shot.

Next test: Correlate the listed frequencies and harmonics with switching regulators, clocks, USB activity, and the transmit centre frequency; vary transmit amplitude to distinguish acoustic/ringdown lines from electrical pickup.

## Strongest random-noise tones

| Frequency | Prominence | Estimated RMS |
|---:|---:|---:|
| 0.009766 MHz | 6.15 dB | -90.61 dBFS |

## Localized regions

| Time | Equivalent depth | Classification | Excess |
|---:|---:|---|---:|
| 37.250–43.650 us | 3.002–3.480 cm | repeatable_coherent_artifact | 7.91 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
