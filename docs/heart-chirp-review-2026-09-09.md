# Heart chirp export review — September 9, 2026

The new file confirms that pulse compression was enabled. Thirteen offline
reconstructions did not establish clearly resolved chamber walls or remove the
lateral arcs. There is measurable deep RF energy above the excluded-channel
comparison; a simple absence of received signal is not a sufficient explanation.

## Files and integrity

- Source: `host/heart-chirp.rf.npz`, exported 2026-09-09 at 14:03:20 local time.
- Matching screenshot: `host/settings/20260909_140323_711624200.png`.
- One sweep, 48 × 9090 signed RF samples. All element records complete.
- No ADC clipping; sample extrema −266 and +279 counts.
- RF SHA-256: `afa36483c88602699097104bb48c1f97f72461ce0aa0666352c4379deca040ca`.
- Results, images, per-trial settings and scripts:
  [comparison report](../bench_runs/heart-chirp-20260909/report.html).

## Recorded configuration

Chirp 0.5 → 8 MHz, requested duration 4.5 µs, quantized burst 4.48 µs;
receive 2–5 MHz; pulse compression on; TGC 1000 → 3678; delay 16 µs;
21% apodization; coherence factor off; one-sweep averaging. The review aperture
angle is 29°, versus 30° at acquisition. Geometry remains the measured CH6-2
geometry, with channels 25/46 excluded. Nominal sequential aperture is 28.09 ms.

The 179-sample saved reference exactly matches the current host command
generator. This rules out a stale duration/reference in replay, but it does not
verify the physical pulse, acoustic impulse response or loaded FPGA bitstream.
The requested receive start follows the transmit burst; analog recovery remains
unmeasured. One frame still takes a sequential aperture to acquire and cannot
establish whether motion within that aperture degrades focusing.

Only 41.1% of the saved electrical reference energy lies in 2–5 MHz; 54.3% lies
in 2–6 MHz. These are discrete commanded-waveform spectrum fractions, not
acoustic energy measurements. An ideal linear sweep over 0.5–8 MHz spends
approximately 1.8 µs of its 4.5 µs duration in 2–5 MHz.

## Actual RF measurements

Median included-channel RMS versus excluded pair, using the same fourth-order
2–5 MHz Butterworth analysis filter on this one sweep:

| Equivalent pulse-echo range | 46 included channels | Channels 25/46 |
|---|---:|---:|
| 6–8 cm | 1.250 | 0.354 |
| 8–10 cm | 1.343 | 0.317 |
| 10–12 cm | 3.786 | 0.415 |
| 12–14 cm | 2.961 | 0.467 |
| 14–16 cm | 1.936 | 0.631 |
| 16–18 cm | 1.355 | 0.836 |

Units are ADC counts. Excluded channels have different electrical terminations
and are not calibrated noise controls. Excess energy may include tissue,
reverberation or clutter; it does not identify an anatomical boundary. Most deep
excess power is around 2–4 MHz, with little excess at 5–6 MHz. Acquisition settings
and probe position differ from older clips, so no causal chirp improvement or
SNR gain is assigned from a between-file comparison.

## Reconstruction trials

Nine production processing variants: saved; compression off; receive 2–4,
1–5 and 2–6 MHz; 75% apodization; coherence exponent 0.15; frequency compounding;
and a combined 2–4 MHz / 75% apodization viewing option.

Four additional offline filters: regularized inverse with floors of 0.10 and
0.03 times maximum in-band reference spectral power; Hann spectral weighting;
and a reference calculated from continuous-time integrals of the FPGA-clock
pulse edges. None demonstrated a clear enough gain to replace production
decoding. Experimental settings files do not themselves implement those filters;
the analysis script and trial JSON specify the method.

The comparison report provides both original display scaling and a common
brightness comparison using one scalar per image in a fixed central region.
Compression-off requires a −15.85 dB offset for that comparison. This is a
processing normalization difference, not a measured SNR gain. No local
normalization or generated detail was used.

Compression produces finer axial texture in parts of this image, but this is
not a point-spread-function measurement. Arcs remain. Narrower reception and
frequency compounding trade axial detail for different texture. Increased
apodization changes off-axis contributions without eliminating the broad arcs.

The [viewing option](../bench_runs/heart-chirp-20260909/review/settings.json)
uses compression on, receive 2–4 MHz, apodization 75%, coherence off, averaging
1, display 85 dB / +27 dB. It is a reproducible visibility option, not a validated
tissue preset. Its acquisition/transmit fields are retained from the recording
and it loads disarmed. For frozen RF, adjust the processing controls directly;
the host acquisition-settings loader requires a new live run.

## Next discriminating experiment

Use the fixed wire bench to compare the current broad chirp with 2–5 MHz at the
same duration and peak drive, plus a short-pulse reference. Hold the position,
gain, delay and receive processing fixed. Measure axial response, range
sidelobes and background before selecting a waveform. Acoustic output and
benefit from concentrating the sweep in-band remain unmeasured.

Capture an isolated, unsaturated wire echo to estimate the actual echo waveform
and delay, then test measured-response matched/mismatched decoding. An unknown
heart reflector is unsuitable for that calibration because overlapping echoes
and reverberation would contaminate the estimated response. Transducer response
and resolution/sidelobe tradeoffs are part of pulse-compression design:
[Misaridis & Jensen, 2005](https://pubmed.ncbi.nlm.nih.gov/15801308/).

No hardware was opened or programmed, and no production host/FPGA algorithm was
changed for this study. All 13 saved magnitudes were checked for finite,
nonnegative values and correct shape; settings were validated and disarmed;
report links and the source RF hash were checked. The source RF and screenshot
remain unchanged.
