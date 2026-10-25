# Fresh weak-echo bench results — 9 September 2026

The requested live acquisition/settings/image loop is complete. The checked FPGA build was restored to RAM, then its nonce and runtime build ID `8841d2b2` were verified before each physical capture. **Nine captures produced 768 complete sweeps.** The study saved 74 reconstructions of physical RF and four explicitly labeled diagnostic reconstructions of time-gated RF.

The result is a more useful starting point for low-level gray detail, with repeatable acquisition and less display saturation. **It is not a tissue-validated preset.** Today's bath did not supply an independently verified faint bubble target. The strongest apparent weak spots beside the wire are consistent with wire sidelobes.

Open `bench_runs/weak-live-20260909/report.html` for images, RF downloads, per-trial settings, linear magnitudes and the diagnostic comparisons. `summary.json` and `rf-summary.json` in that folder contain the measurements and RF hashes.

## Final settings

Load these through **Debug → load settings** in the TFM GL host. Settings files never arm transmission.

| Setting | `host/presets/weak-echo-water.json` | `host/presets/tissue-reference-start.json` |
|---|---:|---:|
| Purpose | Selected current water-bath profile | Unweighted tissue starting reference, unvalidated |
| Sound speed | 1485 m/s | 1540 m/s assumption |
| Receive gain DAC code | Constant 1800 | Constant 1600, retaining extra headroom |
| Receive band | 2–5 MHz | 2–5 MHz |
| Aperture taper | 75% | 75% |
| Coherence exponent | 0.05 | 0 |
| Coherent sweep averaging | 2 | 1 |
| Display dynamic range | 95 dB | 95 dB |
| Display gain | +15 dB, fixed | +15 dB, fixed |
| Gray curve | 1, linear in the log-compressed ramp | 1 |
| Matched filter, frequency compounding, background subtraction, dejitter | Off | Off |

The existing waveform and ±40 V supply were unchanged. Both profiles retain flat transmit trims, the existing 10-channel reconstruction mask, all 48 acquired elements, 15 µs receive delay, 300 µs gap and 14 cm acquisition depth. The delay excludes approximately the first 11 mm in water. The channel mask is an empirical reconstruction choice, not a diagnosis of broken elements.

The tissue reference deliberately avoids coherence suppression and averaging across motion. Its analog gain, depth compensation, display window and assumed sound speed have **not** been optimized on tissue. Water does not reproduce tissue attenuation or establish the required TGC ramp. Earlier preset versions were archived under `bench_runs/weak-live-20260909/previous-presets/`.

## Acquisition findings

The bath was previously reported near 21 °C; temperature was not remeasured. In the current data, the main wire reconstructed near lateral −3.2 mm, depth 40.4 mm, and the strong container echo near 75 mm. Measurements therefore use today's echo positions rather than forcing the earlier approximate 5/10 cm distances.

| TGC code | Sweeps acquired | Largest absolute ADC value | Clipping |
|---|---:|---:|---|
| 1200 | 64 | 649 | None |
| 1400 | 64 | 894 | None |
| 1600 | 256 | 1224 | None |
| 1800 | 320 | 1592 | None |
| 2000 | 64 | 2048 | Seven channels; rejected |

All sweeps passed stream completeness checks. Capture `accepted` indicates complete acquisition, not absence of clipping; gain 2000 was separately rejected on the analog saturation check. Its clipped channel IDs were 32, 33, 34, 40, 44, 45 and 47. The rejected RF is retained for analysis.

Gain 1800 increased echo amplitude relative to 1600, while the median temporal residual in a 47–60 mm sample gate changed only from about 0.318 to 0.329 ADC counts after 2–5 MHz filtering. These captures support a modest sensitivity benefit from the higher gain. The residual includes motion/timing variation and was not measured with transmission disabled, so it must not be presented as isolated electronics noise. The selected gain retains approximately 2.2 dB of ADC headroom relative to the largest observed peak; a different target can change that margin.

Final validation used two new 128-sweep captures at gain 1800 with a 128-sweep gain-1600 control between them. Four frames spread through each capture were reconstructed as an unweighted reference and as the gentle profile. There were no new stream or clipping failures.

## Why the apparent faint spots were not treated as bubbles

Candidate spots appeared near (+18, 37.6) mm and (−21, 36) mm. They persisted after averaging, which alone might suggest real scatterers. A further test changed the interpretation:

1. Predict the wire's round-trip arrival time separately for each element using the current geometry and sound speed.
2. Retain only a ±2 µs window around that arrival, with a 0.5 µs taper, in a **derived** copy of one RF frame.
3. Reconstruct that copy and a complementary copy with the wire window excluded.

With only the wire window retained, the right spot's peak was 14.6 versus 14.9 in the original frame, and the left spot was 6.42 versus 6.35. Excluding the window reduced the search-region peaks to 1.61 and 1.57. The wire itself was also largely removed. This strongly supports a wire-related sidelobe interpretation. Window overlap prevents an absolute proof of target identity, but these are unsuitable independent bubble-validation targets.

No convincing independent faint target was established away from the wire and strong bottom structures. The final presets process the **original RF**, not the gated derivatives. More gray in water can expose noise, sidelobes and reverberation; it is not itself evidence of recovered tissue.

## Processing and display selection

The loop compared receive bands, aperture taper, angular acceptance, coherent averaging, matched filtering, frequency compounding and coherence exponents from 0 to 2. Narrow angular acceptance removed off-axis returns. Strong coherence weighting suppressed much of the low-level image. Those outcomes cannot be called a tissue improvement just because the wire background looks cleaner.

The 2–5 MHz band, 75% taper and gentle exponent 0.05 remain a reasonable water-bath compromise. Two-sweep averaging helps the stationary setup; stronger averaging offers diminishing benefit and can cancel moving echoes. The unweighted single-sweep reference remains the appropriate comparison when assessing subtle tissue gray. The separate diffuse-scatterer software study in `docs/weak-echo-study-2026-09-09.md` also showed why even modest coherence weighting can suppress diffuse returns more than coherent points.

A concrete display problem was measured: at a 70 dB window and +40 dB gain, **5.94%** of pixels in the selected bottom-echo region mapped to solid white. At 95 dB and +15 dB, that fraction was **zero**. Both settings have the same relative black threshold, −110 dB, and the identical fraction of black pixels. All five display trials had **bit-identical linear magnitude arrays**. Thus this change recovers highlight gradation without discarding extra faint pixels, although gray contrast per dB is lower.

The host's display slider and settings validation previously stopped at 80 dB. They now allow up to 100 dB. The default remains unchanged, and no filtering, beamforming or FPGA timing calculation changed for this extension. These numbers describe the display mapping, not a claim of 95 dB receiver dynamic range.

## Reproduction and verification

- `bench_runs/weak-live-20260909/study.py`: bounded capture and rendering helpers; every hardware capture is disarmed after completion.
- `acquire_gain.py`, `sweep.py`, `display_sweep.py`, `validate.py`, `validation_render.py`: trial definitions.
- `wire_gate_check.py`: explicitly labeled RF derivative diagnostic.
- `rf_analysis.py`: per-capture integrity, clipping, temporal residual and hashes.
- `finalize.py`: summary, report and preset generation.

Hardware acquisition uses `bench_runs/control`; replay uses the separate `bench_runs/weak-live-offline` host, which opens no USB device. All saved RF includes the settings, actual commanded transmit reference, runtime identity, configuration readback subset and capture context. The primary data is retained before filtering, averaging or beamforming.

The full host test suite passed **48 tests** after extending the display range. Both presets were also loaded through the running host to check settings restoration and disarmed state. The checked FPGA firmware was restored to RAM; no new FPGA logic or timing build was necessary for this study.
