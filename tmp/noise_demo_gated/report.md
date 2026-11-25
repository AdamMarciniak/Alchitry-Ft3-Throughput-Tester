# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

Assessment gate starts at **3.001 cm** (35.125 µs into the captured waveform). The earlier limiter saturation/ringdown interval is retained as context but is not graded.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 32 |
| Random noise | 7.673 counts (-48.53 dBFS RMS) |
| Repeatable component | 9.661 counts (-46.53 dBFS RMS) |
| Total AC | 12.337 counts (-44.40 dBFS RMS) |
| Peak | 314.0 counts (-16.29 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 146.312 (Gaussian = 3) |
| Effective bits from random noise | 7.268 |

## Excluded near-field context

The ignored interval peaks at 192.0 counts (-20.56 dBFS) and has -33.48 dBFS of repeatable energy. These values do not affect the overall assessment.

## Findings

### MEDIUM: Measured random noise is high relative to ADC full scale.

Next test: Repeat at several fixed TGC values and with the probe/cable substituted to separate input-referred noise from gain-stage or supply noise.

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
| 73.525–80.200 us | 5.874–6.373 cm | repeatable_coherent_artifact | 7.05 dB |
| 47.925–54.325 us | 3.959–4.438 cm | impulsive_or_bursty | 1.79 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
