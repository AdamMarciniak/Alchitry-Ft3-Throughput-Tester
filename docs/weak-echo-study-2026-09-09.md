# Weak-echo replay study — 9 September 2026

**Historical replay phase; the subsequent live loop is now complete.** See [fresh physical results](weak-echo-live-results-2026-09-09.md) for the current presets and measurements. The settings and conclusions below describe the earlier replay phase. Its preset versions are archived under `bench_runs/weak-live-20260909/previous-presets/`.

During this earlier phase, two preflight attempts failed to receive the checked FPGA nonce/build ID. No new physical RF was acquired in that phase and the bench controller did not arm transmission. The programming connection was subsequently restored and the checked firmware reloaded to RAM. A power cycle restoring older flash firmware was a possible explanation, not a confirmed diagnosis.

The current request is to preserve faint tissue and gray detail, rather than optimize the appearance of one bright wire. No tissue phantom or tissue RF is available. Unidentified water-bath targets cannot establish tissue performance, even if they are bubbles.

## Files to load

Use **Debug → load settings** in the TFM host. Loading either file leaves transmission disarmed.

| Setting | `host/presets/weak-echo-water.json` | `host/presets/tissue-reference-start.json` |
|---|---:|---:|
| Purpose | Gentle weak-target water replay candidate | Unweighted, unvalidated tissue starting reference |
| Sound speed | 1485 m/s, prior approximately 21 °C water assumption | 1540 m/s assumption; not a measured value |
| Coherence exponent | 0.10 | 0 |
| Aperture taper | 75% | 75% |
| Coherent sweep average | 2 | 1 |
| Receive band | 2–5 MHz | 2–5 MHz |
| Display range | 70 dB | 70 dB |
| Display gain | +40 dB, fixed | +40 dB, fixed |
| Gray curve | 1, linear in the log-compressed ramp | 1 |
| Matched filter / frequency compounding / background subtraction | Off | Off |

Both retain flat transmit trims, all 48 acquired elements, the prior 10-channel reconstruction mask, constant TGC 1600, 15 µs receive delay, 300 µs gap, 14 cm acquisition depth, and the existing waveform. Those acquisition choices were tested in the earlier water-bath session. They have **not** been established as optimal for tissue. The receive delay excludes roughly the first 11 mm of water. The channel mask is a record of weak channels in those captures, not a diagnosis of broken elements.

The water preset's two-sweep RF averaging is useful for the stationary setup. The tissue reference uses one sweep because coherent averaging across motion can cancel real echoes. No moving-tissue validation has been done. Tissue depth-dependent gain remains untested; water does not supply the attenuation needed to optimize it.

## What was actually tested

79 reconstructions used the production host's filtering, beamforming and compression shaders. The physical source files were:

- `bench_runs/wire-21c-1mm/validation-flat-a/capture.rf.npz`
- `bench_runs/wire-21c-1mm/validation-flat-b/capture.rf.npz`

These are earlier 32-sweep hardware captures, acquired with runtime build `8841d2b2`, valid complete sweeps and no clipped samples in the earlier checks. That build ID describes the original capture, not today's unidentified runtime. Each trial saves the source path, frame, complete settings, linear magnitude array, PNG, and metrics. The original RF remains unchanged.

The study varied coherence exponent 0–2, six alternative receive bands, aperture taper, averaging 1/2/4/8 sweeps, matched filtering, frequency compounding, and display range 60–80 dB. Candidate validation used frames 4, 12, 20 and 28 in each of the two recordings. Some candidate-development frames overlap these checks, so this is repeatability testing, not an independent prospective experiment.

The stable faint feature lies near lateral +13.5 mm, depth 53.4 mm. Its physical identity is unknown. A second weak region near +2 mm, 60 mm changed peak position with processing and averaging. It was excluded from the final target-validation conclusions. An early observation that this region lost about 96% under strong coherence weighting referred to a search-region maximum, not a confirmed individual bubble.

## Findings

- On the same RF frame, changing coherence exponent from 0 to 2 approximately halved the stable faint target's peak amplitude. The wire remained strong. A cleaner black background therefore does not establish better weak-signal preservation.
- The gentle preset retained **85–102%** of the stable faint target peak relative to the reference across eight paired checks. Its peak-to-local-background ratio improved **2.0–3.7 dB**. Both comparisons use the same 75% taper; the gentle preset also averages two sweeps, so changes include averaging and time variation. Values above 100% are not amplification by coherence weighting.
- The 2–5 MHz band was a reasonable compromise. Widening to 1.5–6.5 MHz raised the measured background without increasing the stable faint target. Narrowing to 2–4 MHz reduced target amplitude. These water results do not settle the best band through attenuating tissue.
- Two-sweep averaging preserved the stable target well while lowering background RMS. Eight sweeps reduced the stable target more. Matched filtering and frequency compounding did not improve its local contrast enough to select them in this data.
- Reducing taper from 100% to 75% improved the normalized faint-target level with a manageable arc tradeoff. At 50%, the wider arc became stronger. Raw beamformer sums were normalized for aperture scaling before interpreting this comparison.
- A linear gray curve and wider display range retain more low-level values on screen. They also reveal noise and clutter. They do not create RF information or improve receiver SNR.

The local-background metric includes sidelobes, reverberation, other scatterers and electronic noise. It is **not** an independent electronic-noise measurement. Gray in the water is not proof of tissue sensitivity. Bubble echoes, if present, are not a substitute for distributed weak tissue scattering.

## Separate diffuse-scatterer software check

A deterministic, explicitly labeled simulated RF file was also rendered. It contains 120,000 independent random point scatterers in 2-D, monostatic round-trip delays, a 3.5 MHz Gaussian pulse, fractional sample interpolation and simple element directivity. It models no tissue attenuation, elevation, aberration, measured transducer response, reverberation, nonlinear bubbles or analog electronics. It was not used to claim physical image improvement or clinical performance.

In a fixed diffuse-background ROI, the production renderer gave:

| Coherence exponent | RMS amplitude retained relative to unweighted | Median amplitude retained |
|---|---:|---:|
| 0 | 100% | 100% |
| 0.1 | 76% | 71% |
| 0.2 | 58% | 50% |
| 2 | 1.5% | 0.10% |

This software example explains why preservation of a faint coherent point is insufficient to choose a tissue preset. The unweighted reference is essential. Known brightness and texture effects of coherence weighting are also discussed in the primary paper [Spatio-temporally smoothed coherence factor for ultrasound imaging](https://ieeexplore.ieee.org/document/6689786/). Our numerical values come from the local model, not that paper.

## Artifacts and reproduction

- `bench_runs/weak-echo-20260909/report.html`: image comparisons and all trial links.
- `bench_runs/weak-echo-20260909/study-summary.json`: physical-RF replay metrics and paired checks.
- `bench_runs/weak-echo-20260909/SIMULATION-diffuse-summary.json`: separate software-model results.
- `bench_runs/weak-echo-20260909/study.py`, `sweep.py`, `candidates.py`, `validate_candidates.py`: replay trial definitions.
- `bench_runs/weak-echo-20260909/diffuse_check.py`: deterministic model, seed and limitations.
- `bench_runs/weak-echo-20260909/finalize.py`: preset and HTML report generation.

Start an offline host with `python tools/bench.py --control-dir bench_runs/weak-offline start --sim`, then run the study scripts. Existing trial results are reused only when their settings, frame and source agree. Simulation mode opens no USB device. The report labels the physical data as replay and the model as simulation.

## Controller fix and remaining live work

The long replay loop exposed a transient Windows destination-file lock while atomically publishing `server.json`. The controller stopped and remained disarmed. JSON replacement now retries only the relevant Windows permission/sharing errors, for a maximum of 150 ms, preserving the old complete JSON throughout. Persistent failures still raise an error. Two regression tests cover recovery and bounded failure; the full host suite passed **48 tests**. The replay loop resumed successfully.

After the programming connection is restored, the next required work is to verify the running FPGA identity, acquire fresh unweighted RF with the current water setup, locate repeatable faint targets, compare receive gain without clipping the container bottom, and validate the candidate on newly acquired sweeps. Do not bypass the identity check or infer success from the old programming receipt. The existing checked build is `bench_runs/builds/20260908T012733Z-41017f`; no new FPGA build is required for the processing changes above.
