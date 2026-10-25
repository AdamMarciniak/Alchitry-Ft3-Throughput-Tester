# CH6-2 image-quality investigation

Prepared 2026-09-07 from the current host/FPGA source and the owner's circuit clarifications. This is a staged bench procedure, not a diagnosis of the heart image. Start with Experiment 1; later stages depend on its results.

## Confirmed physical configuration

- CH6-2, measured geometry, centre 48 elements; one element transmits and receives per shot.
- Three leaf muxes have all 16 COM inputs connected within each bank. Only three root COM inputs are connected; its other 13 solder gaps are open.
- Selected element → two MAX14866 switches → MD0100 → BAV99T clamp → 4-inch SMA cable → 33 Ω series resistor → BAV99 clamp → 100 nF coupling capacitor → AFE5804.
- AFE.R13 is **not populated**. PULSER.C24 and C25 are solder bridges. The U3/ground drawing ambiguity is resolved; do not treat it as a confirmed fault.
- Measured gain-control voltage is 0–1.2 V. ADC has its own 40 MHz oscillator. Supply setting is ±40 V.
- Air-derived transmit trims were created with waterfall auto-cal. Suspected open-element outliers are not evidence of healthy-channel timing error. Their exact identifiers have not all been supplied.

## What the current applications actually do

- The B-mode host is `host/tfm_gl_host.py`.
- With hardware connected, the B-mode host now starts with **PULSER RUN off**. Configure the bench before starting a run.
- **FREEZE freezes the cine buffer, not transmission.** After freezing, uncheck **PULSER RUN** to stop firing while reviewing.
- Cine contains RF sweeps in memory. Changing coherence, curve, bandpass, aperture weighting, and several receive controls can reprocess the same frozen frame.
- **Shift-click save settings** adds a note and saves timestamped JSON plus a matching PNG under `host/settings/`. These are not raw-RF exports.
- **Save RF…** now exports full-array RF, references, settings, context, and quality flags. **Open RF…** restores it for review. Unsaved cine remains volatile. See [the RF harness guide](rf-debug-harness.md) for the complete save/replay workflow.
- The **dead** field accepts physical element IDs separated by commas; press Enter. The default excludes only element 46. Exclude other elements only when their identity is established.
- Pulser settings, analog TGC, and transmit trims are acquisition settings. They cannot be changed retrospectively in recorded data.

## Experiment 1 — Determine what coherence processing does

### Target and setup

1. Use the existing wire in water, held perpendicular to the image plane, around 5–7 cm from the probe face. Fix the probe and wire so neither moves.
2. Couple the probe face to the water while keeping connectors and electronics dry. Keep other strong boundaries outside the target region where practical.
3. The existing 3 mm wire is adequate for comparing arcs. A roughly 0.1–0.3 mm filament/wire is preferable later for estimating the point response; record its diameter/material. Neither target measures tissue-texture preservation by itself.
4. Record approximate water temperature and target distance. Use water sound speed appropriate to temperature: about 1482 m/s at 20 °C or 1497 m/s at 25 °C. Keep measured pitch and radius unchanged. Reference: [NPL water sound-speed guide](https://resource.npl.co.uk/acoustics/techguides/soundpurewater/).
5. Keep the current transmit waveform, trim table, and acquisition timing for this first comparison. The aim is to vary processing alone. Keep the existing ±40 V setting.

### Establish a reference image

Use these actual B-mode control names:

| Control | Initial comparison value |
| --- | --- |
| depth | Enough to include the wire and some space beyond it; 10 cm is suitable for a wire at 5–7 cm |
| coh | 0% |
| curve | 100% |
| auto gain | Off |
| dyn range | 80 dB |
| gain | Adjust once so the wire is visible and its core is not broadly white/saturated; then hold fixed |
| apod | 74% for this comparison |
| aperture | 30°; this is element acceptance angle, not physical array width |
| bandpass | On; centre 4.0 MHz, bandwidth 5.0 MHz gives nominal 1.5–6.5 MHz |
| avg | 1 sweep |
| freq compound | Off |
| pulse comp | Off |
| bg subtract | Off |
| de-jitter | Off |
| dead | Confirmed failed-element IDs only |

These values define an experiment, not an optimized imaging preset. If the receive waveform is clipping, reduce analog gain before proceeding; lowering display gain cannot fix clipped RF. The existing near-level meter is a useful screen, but is not a substitute for full-trace clipping checks.

1. Acquire a few seconds with the stationary wire.
2. Click **FREEZE**, leave playback paused on one frame, and uncheck **PULSER RUN**.
3. Shift-click **save settings**. Note: `wire baseline; coh 0; [diameter, depth, water temperature]`.
4. Change only **coh** to 36%. Save again with `wire same frame; coh 0.36`.
5. Change only **coh** to 120%. Save again with `wire same frame; coh 1.2`.
6. Return **coh** to 0%. Leave the app open if the frozen RF is still needed.

Do not change gain, dynamic range, frame, or target position between these saves. The slider uses percent; 120% corresponds to exponent 1.2.

### Interpretation

- If coherence removes arcs but also strongly reduces the target, the wanted echo has limited coherence; distinguish timing/focus error from the target's finite size and scattering behavior.
- If coherent weighting produces a tidy point while the plain image has large arcs, it is concealing some of the unweighted response. This does not identify an electrical fault by itself.
- If all versions retain similar broad arcs, investigate aperture response and calibration next.
- A wire image cannot establish whether real tissue texture has been lost. That question eventually requires distributed scattering, preferably a stationary tissue-mimicking phantom.

Optional second comparison on the SAME paused frame: with coh=0 and other controls fixed, save apod=0%, 50%, and 100%. Compare target width against relative lobe level. The host changes its global full-scale reference with apodization, so these images are useful for shape comparisons, not direct absolute sensitivity measurements.

## Experiment 2 — Validate timing calibration

Prepare a reversible flat/loaded trim comparison before running it. Back up `host/settings/trim.json`; do not overwrite the only calibration copy. The B-mode GUI currently has no simple loaded/flat trim comparison control, so this stage benefits from a small software addition.

- Use a fixed small target at a known position, with coherence, background subtraction, de-jitter, compounding, and RF averaging disabled initially.
- Capture separate datasets with the saved trims and a flat table. Keep pulse waveform, TGC, geometry, temperature, and target position fixed.
- A flat table still needs the same common transmit bias used by the host; zeroing raw FPGA entries is not equivalent to the host's flat-table operation.
- Fit/allow a common time offset in each reconstruction. Compare residual per-element arrival error, target width, and lobe level; do not mistake a global range shift for defocus.
- Use predicted arrival times t_i = 2*distance(element_i,target)/c + common_offset. Any calibration correction should remove residual error after this geometry, not the physical path differences.
- Validate on a second target position/depth not used for fitting. Improvement at the calibration target alone is insufficient.

Do not auto-align a wire trace to a horizontal line in waterfall. Even a flat reflector has element-dependent travel times for this convex array. The current automatic routine has no geometry model. Air calibration is a useful repeatability reference, but feedthrough/ringdown propagation may differ from the wanted echo path.

## Experiment 3 — Separate noise, pulse shape, and texture

These are separate comparisons, each changing one factor.

1. **Noise:** on a stationary target, compare avg=1 and avg=8. Use repeated RF to estimate random residual noise separately from the repeatable mean waveform. A quieter-looking display or the host's broad far-RMS number is not itself an SNR measurement. Do not transfer coherent averaging results directly to a moving heart.
2. **Pulse:** establish an uncoded reference with chirp off, pulses=2, width=100 ns, dead=40 ns, pulse comp off. The nominal full-cycle frequency is about 3.57 MHz at a 100 MHz sequencer clock. Acquire fresh data after changing transmission. Preserve the existing settling/inhibit timing.
3. **Chirp:** compare a short chirp with compression off/on on the SAME chirp dataset. Initially keep the chirp duration near the existing 1 µs; increasing duration changes energy and is not a neutral comparison. The harness locks transmit controls during review and uses the reference saved with an RF file.
4. **Texture:** on distributed scattering, compare freq compound off/on with coh=0. Look for reduced graininess together with any increase in reflector thickness. Validate useful contrast, not just smoothness.

## Software work that makes the bench session reproducible

The first useful additions are:

1. Export/import full-array RF and acquisition metadata, including actual transmitted waveform/trim table, sample rate, geometry, element mask, TGC, code/build identity, and transport counters.
2. Keep recorded acquisition metadata attached to replay; never derive the compression reference from unrelated live transmit settings.
3. Compare ordinary DAS, coherence map, and weighted image with controlled display references.
4. Add loaded/flat trim switching with explicit new-acquisition boundaries, and geometry-aware acoustic calibration.
5. Report clipping across the whole receive window and per-element health. Mask confirmed failed elements in calibration references as well as reconstruction.
6. Log sample losses, missing shots, and ADC-grid synchronization fallback; make unreliable acquisitions identifiable.

The host RF harness now implements export/import, settings restoration, attached acquisition metadata, saved references, DAS/CF comparison views, flat-trim switching, and per-element/transport reports. No FPGA change is required for manual save/replay. The [automated wire bench](autonomous-wire-bench.md) additionally provides checked builds, RAM programming, bounded captures, a firmware identity/configuration query, and measured image experiments. Geometry-aware acoustic calibration and ADC fallback telemetry remain future work. See [the workflow and format details](rf-debug-harness.md).

## Hardware measurements after the processing comparisons

Choose probe connections after identifying the available oscilloscope and probe ratings. Use a stationary bench target for these measurements.

| Measurement | Purpose |
| --- | --- |
| Loaded PULSE_OUT waveform, including receive interval | Actual pulse shape, ringing, baseline recovery |
| Repeated stable target echo relative to transmit, one healthy element at a time | Shot-to-shot timing repeatability and channel response |
| Protected receive signal at RF2 and AFE input-side network | Localization of attenuation, pickup, or prolonged recovery |
| Selected element impedance and mux-path response across the receive band | Quantify capacitive loading rather than infer it from brightness |
| Analog rails and gain-control waveform during receive | Identify synchronous disturbances and gain-ramp artifacts |

- Oscilloscope probe capacitance can change the very node being investigated; account for it.
- Transistor gate-to-source measurements are floating measurements. Use appropriately rated differential equipment; do not attach a grounded probe clip to a ±HV source or defeat scope protective earth. Reference: [Tektronix floating measurement guide](https://www.tek.com/en/datasheet/floating-measurements-selection-guide).
- Small-signal impedance/transfer measurements require the HV source disconnected and discharged, with appropriately isolated or de-embedded signal injection. Exact connections depend on the instrument; do not connect a VNA/function-generator input directly to a node that can transmit HV.
- Turning PULSER RUN off clears mux selection, so a no-transmit measurement of a selected path needs a defined receive-only/static-mux mode. Pulser-off is not automatically a matched-load noise baseline.
- Do not remove protection components or ground returns to see whether the image improves. Assess return-current paths with board layout and a controlled bench configuration.

## Decision after evidence is collected

| Finding | Next direction |
| --- | --- |
| Plain reconstruction preserves useful scattering; CF removes it | Gentler/bounded coherence weighting and display changes |
| Corrected calibration improves a second target position | Geometry-aware calibration and stable timing reference |
| Ideal and measured point responses have similar arcs | Aperture/sampling/weighting limitations; acquisition architecture |
| Healthy-channel echoes are close to measured receiver noise | Receive loading, lower-noise front end, suitable pulse spectrum |
| Pulse shape or recovery differs materially across paths | Analog network, damping, mux/protection behavior |
| Transport or timing counters fail | FPGA acquisition integrity before image processing |

For a hardware redesign, smaller mux banks with separate protected receive channels deserve evaluation. More receive channels require corresponding routing, ADC capture, transport, and beamforming changes; they cannot be enabled by software on the present single-channel connection alone.

## First result to review

The Experiment 1 RF recording and its report, the three timestamped JSON/PNG comparison pairs, and the wire diameter/depth and approximate water temperature. Use timestamped files rather than only `latest.json`. This first set identifies the effect of coherence processing; it does not settle weak-tissue sensitivity.
