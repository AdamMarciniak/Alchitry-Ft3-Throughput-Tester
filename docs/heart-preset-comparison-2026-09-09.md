# Three heart preset clips — September 9, 2026

The clips establish that the requested gain ramp affects the recorded data, but do not establish a consistently better tissue image. The user reports some probe movement between presets, with an uncertain amount; earlier context includes rib shadowing. Acoustic view and cardiac phase therefore confound direct between-clip comparisons.

Open the [comparison report with cine previews](../bench_runs/heart-presets-20260909/report.html).

| Clip | File in host/ | Complete sweeps | Duration | Clipped ADC samples |
|---|---|---:|---:|---:|
| Baseline | heart-baseline.rf.npz.rf.npz.rf.npz | 188/188 | 4.989 s | 0 |
| Start | heart-start.rf.npz.rf.npz.rf.npz | 127/127 | 3.350 s | 0 |
| TGC | heart-tgc-latest.rf.npz.rf.npz.rf.npz | 189/189 | 5.025 s | 0 |

All three use 48 elements, 8020 samples per element at 40 MSPS, receive delay 16 microseconds, gap 313 microseconds, identical commanded chirp and geometry, and excluded channels [25,46]. RF SHA-256 and ZIP CRC were verified for all files. The per-sweep quality records are complete; lifetime host timeout/resync counts are not evidence of losses inside these selected clips. Manual metadata does not read back the active bitstream or analog voltage.

Baseline and Start have identical acquisition settings. Start changes only receive band 2–5 to 2–4 MHz and display 95 dB/+15 dB to 80 dB/+30 dB. TGC changes only acquisition gain from 1600/1600 to 1000/3400. Its saved review additionally changes the display curve from 1 to 0.67. Common reconstructions remove all these processing/display differences, including the curve adjustment.

## RF findings

Median RMS across 46 included channels, using the same fourth-order 2–5 MHz Butterworth analysis filter and 64 evenly spaced valid sweeps per clip:

| Equivalent pulse-echo range | Baseline | Start | TGC |
|---|---:|---:|---:|
| 5–6 cm | 0.944 | 0.943 | 4.250 |
| 6–8 cm | 0.534 | 0.563 | 1.274 |
| 8–10 cm | 0.467 | 0.410 | 0.633 |
| 10–12 cm | 0.947 | 0.623 | 0.738 |
| 12–14 cm | 0.434 | 0.512 | 0.780 |
| 14–16 cm | 0.338 | 0.339 | 0.728 |

Units are ADC counts. Range assumes 1540 m/s and the saved delay. These are signal-plus-noise amplitudes, not beamformed SNR or verified anatomical depths.

Quiet channels 25 and 46 stay around 0.32 counts in the two flat-gain clips. In TGC their median rises from 0.305 at 1.3–2 cm to 0.661 at 14–16 cm, consistent with a gain ramp. At that far range, included-channel RMS is only 0.728, so increased brightness is largely consistent with amplified noise. The quiet pair is not a calibrated noise-only measurement for every connected element.

TGC is stronger around 5–6 cm but weaker than baseline around 10–12 cm. Gain cannot be isolated from changing views. The new baseline also contains more 10–12 cm power than the earlier 956-sweep recording (0.947 versus approximately 0.353 counts at the same nominal acquisition settings). That is substantial capture-to-capture variability, not proof of a fixed electronics cutoff.

## Reconstruction and motion

Twenty-one still renders and 127 cine-preview frames use the production receive pipeline and shaders. Common display: 2–5 MHz, CF0, averaging1, apodization0.75, excluded[25,46], 95 dB/+15 dB, curve1. The GIF previews sample every fourth RF sweep, with duration based on the nominal 26.64 ms aperture period. Clips loop independently and are not synchronized to each other or to cardiac phase.

Broad echoes and arcs are present; convincing chamber boundaries were not established. Increased gray level is not by itself evidence of resolved tissue. No health conclusions or anatomical labels are assigned. Wire-specific metrics emitted by the harness were not used as tissue scores.

A bounded adjacent-frame RF time-shift search (+/-2 microseconds, 32 pairs per clip, 2–4 MHz) did not reveal a reliable global correction. In TGC at 4–6 cm, median normalized correlation increases from 0.014 at zero lag to 0.364 after searching; the quiet-pair search gives 0.222. At 8–12 cm it reaches only 0.190 versus 0.160 for the quiet pair. Searching itself raises random correlations. These numbers mix motion, noise and changing scatterers; they do not measure velocity or establish a timing defect.

## Decision

Retain the current presets as references. Start is a display/filter option, with no acquisition sensitivity advantage over baseline. The TGC preset has a limited successful capture check (189 complete sweeps, no clipping) but is not tissue optimized. Its validation notes were updated without changing operational fields.

Further work should examine transmit/receive architecture and acquisition time on the fixed water bench, alongside actual AFE gain-waveform and connected-channel noise measurements. A later manual tissue comparison should use a supported unchanged position and baseline–TGC–baseline sequence, with processing fixed, to check for view drift. The current 26.64 ms sequential aperture remains a possible motion limit; earlier short-gap water tests lost elements, so faster timing is not yet validated.

Scripts, raw-data hashes, source paths, settings, exact frame selections and measured statistics are preserved in `bench_runs/heart-presets-20260909`. All work on these clips was offline; source RF was read-only. No hardware acquisition or FPGA programming occurred.
