# Heart RF engineering review — September 9, 2026

The captured RF becomes very weak with range. None of the offline reconstruction trials recovered convincing chamber detail. The user's observation that the live image was mostly faint speckle agrees with the replay. Brightening it makes that grain easier to see, but does not establish that tissue structure has been recovered. This is an image-formation assessment, not an interpretation of heart health.

Open the [image comparisons and plots](../bench_runs/heart-review-20260909/report.html). Everything in this review used the existing recording offline. No hardware acquisition, transmit change or FPGA programming occurred.

**Additional user context:** the probe moved slightly during this recording while the user sought a better view, and ribs sometimes blocked the deeper signal. Motion and acoustic shadowing are major confounders: the observed deep signal deficit does not isolate an electronics fault or establish that TGC will solve it. The ultrasound is now off, and the user will make the next captures manually.

## Recording and measurements

Source: `host/heart-recording.rf.npz.rf.npz`, saved at 09:58 local. RF SHA-256: `7f1c1d07920233553dd03d1c1a750f637db324502d8a36c1d3eedb50ab3e52e3`.

- 956 complete sweeps over 25.526 seconds; 48 elements × 8020 signed ADC samples per sweep, at 40 MSPS. All sweep quality records are valid. Full RF checksum and ZIP CRC verified.
- Full-recording clipping check found **7 samples** at the ADC rails, in frames 27–29 on zero-based channels 2–4, at equivalent ranges of 13.90–14.13 mm. Widespread clipping is not the cause of the faint image.
- Saved receive gain was **TGC 1600 → 1600**, flat across the window. Receive delay 16 µs, window 200.5 µs, gap 313 µs, nominal depth setting 15 cm.
- Saved reconstruction: 1540 m/s, measured R=67.52 mm and pitch=0.3375 mm, 30° acceptance, 75% apodization, CF exponent **0**, no RF averaging, receive band 2–5 MHz. Only channels 25 and 46 excluded.
- Display: 95 dB, +15 dB, gamma/curve 1, automatic gain off. Coherence suppression was already disabled, so switching it off cannot fix this recording.
- Chirp enabled, requested 5.2 → 2.6 MHz over 1 µs, flat trims. The saved commanded waveform lasts 1.04 µs with a spectral peak around 3.77 MHz. In the current RTL, a nonempty chirp table takes precedence over fixed-burst cycle/width fields; the saved `n_cycles=1` and `t_drive_ns=50` do not establish a shortened chirp. These are command/reference values, not measurements of emitted acoustic energy.
- The metadata describes host requests. This manual capture did not attach runtime FPGA identity/configuration readback. Historical water/wire setup notes are not measurements of the heart target.

Depth-resolved RF measurements use 64 evenly spaced sweeps, a fourth-order Butterworth bandpass, and RMS calculated per channel before taking the median across the 46 included channels. These are **not beamformed SNR measurements**. Range assumes the saved 1540 m/s and 16 µs offset; on a curved probe it is equivalent pulse-echo range, not a verified anatomical coordinate.

| Equivalent range | 2–5 MHz, 46-channel median RMS | Quiet pair median RMS |
|---|---:|---:|
| 2–3 cm | 16.14 counts | 0.323 counts |
| 3–4 cm | 3.47 | 0.320 |
| 4–5 cm | 1.51 | 0.317 |
| 5–6 cm | 0.77 | 0.319 |
| 6–8 cm | 0.54 | 0.320 |
| 8–10 cm | 0.35 | 0.317 |
| 10–12 cm | 0.35 | 0.319 |
| 12–14 cm | 0.34 | 0.324 |

The quiet pair is channels 25 and 46. It is a useful comparison, **not a calibrated noise-only measurement for every connected element**. The data support little deep amplitude margin over that comparison. They do not determine whether input noise, ADC/downstream noise, weak acoustic returns, coupling/window, or more than one factor dominates. Strong shallow returns do not by themselves distinguish tissue echoes from reverberation or transmit recovery.

## What replay changed

The study saved 25 rendered comparisons with linear magnitudes, PNG images, settings and exact patches. Five original frames span the recording; four frames also use the review alternative. The production host receive pipeline and OpenGL shaders generated the images. RF remained unmodified.

Trials included several bands, increased display brightness, weak coherence weighting, the coherence map, frequency compounding, matched filtering, two-sweep RF averaging, altered apodization, the earlier water channel mask, and central 24/16-element subsets.

The **2–4 MHz** band is a modest review alternative. At 4–5 cm its channel median is 1.31 counts against a 0.259-count quiet comparison; at 8–10 cm it is 0.297 against 0.260. It changes the noise/resolution balance but does not recover a clear chamber image. The 80 dB / +30 dB display setting mainly increases visible grain. Both this and the original 95 dB / +15 dB setting put black at approximately −110 dB relative to the renderer reference; the changes redistribute gray levels, not receiver sensitivity.

Compounding smooths the texture, and other options change grain/arcs, without establishing useful anatomy. The central subsets shorten the time span represented by the contributing shots but also reduce aperture and alter display normalization. They cannot be interpreted as a measured SNR gain. The harness's saved wire-width/clutter metrics are inappropriate tissue scores and were not used for ranking this recording.

Do not restore the earlier ten-channel water mask automatically. Most of those channels have substantial shallow/midrange signals in this file. Keep the capture's [25, 46] mask pending a connected-channel test; this does not prove those two elements are physically open.

## Concrete next comparison

Three loadable settings files are supplied:

1. [Captured baseline](../host/presets/heart-recording-baseline.json): restores the operational settings from this recording, disarmed.
2. [Untested analog TGC comparison](../host/presets/heart-tgc-next-test.json): changes **only TGC from flat 1600 to 1000 → 3400**. Transmit waveform, timing, receive processing, geometry and display match the baseline. Image improvement and actual analog ramp are unvalidated.
3. [Review/display alternative](../host/presets/heart-review-start.json): keeps the captured acquisition but uses 2–4 MHz, 80 dB / +30 dB. This is not an optimized tissue preset.

For an acquisition settings file, choose **new live run → load settings…**. Loading leaves **PULSER RUN off**. A recorded RF file retains its original acquisition; no settings file can retrospectively apply analog gain to it. During replay, the review alternative is available through the normal band/display controls: band center 3 MHz, bandwidth 2 MHz, dynamic range 80 dB and gain +30 dB.

First verify the gain ramp on the water bench with an oscilloscope at AFE VCNTRL, triggered by transmit or receive timing. With the reported 0–1.2 V DAC span, the proposed endpoints are approximately **0.293 → 0.996 V**. The slope should occur during the receive window, then return to the starting level for the next element. This verifies actual analog behavior as distinct from successful settings loading.

The AFE5804 specifies nominal gain slope 44.4 dB/V over its 0.1–1.0 V control region. Using that slope, this proposal is approximately −7.8 dB relative to flat1600 at the window start, +10 dB around 10 cm equivalent range, and +23.4 dB at the end. These are estimates, not measured gains. More gain before digitization may help when ADC/downstream noise is limiting; it also amplifies input noise and cannot recover echoes absent at the receiver input. [TI AFE5804 datasheet](https://www.ti.com/lit/ds/symlink/afe5804.pdf).

For the next manual paired capture, find the clearest acoustic window, hold the probe still, and compare baseline versus TGC ramp from the same position with everything else fixed. A single RF frame is useful for reconstruction comparisons; a short stationary clip is better for checking persistence and noise if practical. Save both RF files before further settings changes. Inspect **all-frame clipping**, power by range, and repeatable structure relative to the background. Brightness alone is not success. A matched transmit-off noise recording on the same connected channels can characterize electronics, but it will not reproduce transmit-induced recovery or acoustic reverberation. If the gain change only lifts noise, prioritize acoustic coupling/window and the probe–mux–protection–AFE signal chain.

The current FPGA already implements the linear gain ramp using a timebase independent of USB drain timing, so this comparison needs no FPGA modification. There is no evidence here that just increasing pulser voltage or adding an LC network would solve the problem. An LC matching proposal needs impedance/bandwidth and ringdown measurements first.

## Motion and later work

The saved command timing spans approximately **26.64 ms per sequential 48-element aperture**. Host timestamps arrive in batches and are not per-element timing measurements. Motion during a synthetic aperture can impair coherent summation; compensation methods address this, but this recording cannot isolate motion loss from low signal level. [Primary study of synthetic-aperture motion compensation](https://pubmed.ncbi.nlm.nih.gov/12199420/).

For reference, 256 consecutive sweeps have adjacent-sweep zero-lag RF correlation about 0.40–0.42 at 4–8 cm and only 0.060 at 8–12 cm in the 2–4 MHz band. Low SNR and motion both reduce correlation; clutter can increase it. These numbers do not measure cardiac velocity. Keep coherent RF averaging at one and CF weighting off while resolving the signal deficit.

A faster aperture or motion correction is worth revisiting after the gain/SNR comparison. Do not blindly shorten the 313 µs gap: an earlier short-gap water experiment produced incomplete element sweeps. Any timing change needs bench verification of complete data, range timing, mux settling and gain reset before judging its image effect.

## Debugging changes and reproducibility

- Ordinary RF archives now open through a **read-only memory map inside the archive**, avoiding the extra 737 MB extraction that failed on this machine's remaining disk space. Complete RF SHA-256 and ZIP CRC validation remain enabled; compressed archives retain the extraction fallback. Close a mapped source before replacing it on Windows.
- Bench startup handles immediate Windows reuse of the previous process ID.
- `python -m unittest discover -s host -p test_*.py`: **52 tests passed**, including corruption rejection, exact RF round trips, compressed fallback, settings disarm behavior and simulation host tests. No test opens hardware.
- [Analysis scripts and measurements](../bench_runs/heart-review-20260909/) preserve the measurement methods. `rf_analysis.py` checks all-frame clipping and sampled depth/band power; `temporal.py` calculates the declared temporal statistics; `study.py`/`sweep.py` generate offline comparisons; each render has `trial.json`, `settings.json`, `magnitude.npy`, and images.
