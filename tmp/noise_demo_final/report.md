# Single-element noise analysis

Overall triage: **investigate**

Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.

## Core measurements

| Measurement | Value |
|---|---:|
| Frames | 64 |
| Random noise | 6.607 counts (-49.83 dBFS RMS) |
| Repeatable component | 29.622 counts (-36.79 dBFS RMS) |
| Total AC | 30.350 counts (-36.58 dBFS RMS) |
| Peak | 327.0 counts (-15.94 dBFS) |
| Clipped samples | 0.00000000% |
| Residual kurtosis | 121.036 (Gaussian = 3) |
| Effective bits from random noise | 7.483 |

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
| 0.000–12.800 us | 0.374–1.331 cm | repeatable_coherent_artifact | 17.57 dB |
| 64.000–80.200 us | 5.161–6.373 cm | repeatable_coherent_artifact | 8.07 dB |
| 44.800–51.200 us | 3.725–4.204 cm | impulsive_or_bursty | 3.93 dB |

## Important interpretation notes

- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.
- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.
- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.
- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.
