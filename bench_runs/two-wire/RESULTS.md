# Two-wire gelatin RF optimization — 2026-11-24

Source RF: `C:\Users\Adam\usb3-tester\gelatin-2-wires.rf.npz`

## Finding

The dominant horizontal smear came from the non-flat per-element transmit-trim
table. The FPGA moves each element's echo by the programmed trim, while the
ordinary beamformer assumes a common transmit time. Direct fits to the two echo
arrival curves had about 105 ns RMS residual with the saved timing and 20 ns RMS
after removing the programmed relative trims.

The source RF was preserved. A derived replay session removes the relative
per-element trims by fractional time shifting and retains the fixed 2 us
hardware bias in `t0`:

`C:\Users\Adam\usb3-tester\bench_runs\two-wire\gelatin-2-wires-trim-comp.rf.npz`

## Selected live settings

- Full 48-shot, one-cycle SAFT; dead elements 25 and 46 excluded
- Flat per-element TX trim; `t0 = +1900 ns`
- `c = 1490 m/s`, `R = 67.0 mm`, `pitch = 0.333 mm`
- Acceptance 22 degrees, rectangular aperture (`apod = 0`)
- Receive band 1.5–7.5 MHz (`f0 = 4.5 MHz`, width 6 MHz)
- Frequency compounding off, matched filtering off, averaging 1 sweep
- Coherence exponent 0.15, dynamic range 66 dB, gain +25 dB, curve 0.90
- AFE remains CH1-only, PGA 30 dB, +6 dB CH1 digital gain, 12.5 MHz LPF

Preset: `C:\Users\Adam\usb3-tester\host\presets\gelatin-two-wire-best.json`

## Finite-wire measurements

The original review selected a different bright peak for the left wire. The
previously reported 0.99 mm left-wire baseline cannot support a before/after
comparison. On the timing-corrected RF, the same two targets measured
0.67/0.93 mm laterally under the baseline ordinary delay-and-sum settings
and 0.56/0.76 mm after focus tuning. Those figures describe the displayed
response of the two finite wires.

On a finer, equal-axis grid, coherence 0.15 gave lateral −6 dB widths of
0.50/0.68 mm for the wires at depths of 18.65/20.10 mm. Coherence 0.35
gave 0.45/0.61 mm at the same positions and reduced signal beside the wires
by about 4.7 dB. Median gelatin signal was 6.6–6.9 dB lower in two patches.
Both views use the same display gain and grayscale. A held-out-element check
on the original RF measured 119 ns RMS arrival-time error using a common
transmit time and 19 ns when accounting for the recorded element delays.
The 23–33 µs wire gate had zero clipped samples on the 46 usable elements.

## Ready-to-open RF

Use **Open RF** in TFM GL. Both sessions include timing-corrected samples,
the original acquisition metadata, and the selected review controls. Each
reproduced the corresponding measured beamformer magnitude exactly in the
host's default bench render with no additional settings applied.

- [Wires and gelatin, coherence 0.15](gelatin-two-wire-balanced.rf.npz)
- [Wire detail, coherence 0.35](gelatin-two-wire-wire-detail.rf.npz)
- [Same-gain comparison](final-settings/comparison.png)
- [Fine-grid measurements and gelatin regions](final-settings/measurements.json)
- [Original RF timing and clipping](focus-check/raw_check.json)

## Files

- Before/after image: `C:\Users\Adam\usb3-tester\bench_runs\two-wire\two-wire-before-after.png`
- Raw element/time envelope: `C:\Users\Adam\usb3-tester\bench_runs\two-wire\rf-element-envelope.png`
- Complete sweep results: `C:\Users\Adam\usb3-tester\bench_runs\two-wire\search-20261124-v4-corrected\analysis.json`
- Selected corrected replay settings: `C:\Users\Adam\usb3-tester\bench_runs\two-wire\search-20261124-v4-corrected\selected-settings.json`

## Hardware state

The prior live host was stopped cleanly and disarmed. On restart, Windows no
longer enumerated an FT601/FTDI/Alchitry USB interface, so the host correctly
fell back to simulation; that simulation was stopped. Windows device rescan was
also denied by the OS. Replug or power-cycle the FPGA/FT601 USB connection, then
start:

`python host\tfm_gl_host.py --settings host\presets\gelatin-two-wire-best.json --arm`

The guarded startup saves `bench_runs\live-settings.png`,
`bench_runs\live-settings.rf.npz`, and `bench_runs\live-settings-startup.json`
after verifying live RF flow.
