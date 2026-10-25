# Automated CH6-2 wire bench

The bench harness can build and check FPGA firmware, temporarily load an Alchitry Au V2, acquire bounded RF recordings, restore settings, render the same RF with different processing, and save a measured comparison report. Once the probe is fixed on the wire and both USB links are ready, these operations can be controlled from this task without moving sliders or manually taking screenshots.

The automatic search currently changes receive processing and reconstruction. Acquisition timing, TGC, and trim experiments are available through the control interface and require fresh RF for each condition. Firmware experiments use a new checked build followed by the same capture/analysis workflow. The runner does not change the HV supply or automatically search transmit waveforms.

## What has actually been checked

- 46 Python tests passed, covering an independent simulation host process, control messages, settings-file restoration, RF round-trip, GPU rendering, firmware-response validation, uploader enumeration, and failure cases.
- The actual FPGA control decoder passed an RTL simulation of boot-disarmed behavior, lease renewal/expiry, blocked rearming after expiry, and the disarmed identity response.
- Vivado 2025.2 completed synthesis, placement, routing, and bitstream generation for `xc7a35tftg256-2`. The checked build is `bench_runs/builds/20260908T012733Z-41017f`, runtime tag `8841d2b2`. Worst setup slack is **0.421 ns**; worst hold slack is **0.025 ns**. There are no failing design-rule checks, no unclocked clock pins, and no unconstrained internal endpoints in its timing report. These margins apply to the supplied constraints, not to unmeasured external analog timing.
- The complete settings-load, fresh-capture, processing-search, and separate-frame validation workflow ran using **simulation**. The latest report is [here](../bench_runs/experiments/20260909T005902Z-1ec66c/report.html).
- Physical follow-up successfully programmed the Au V2 RAM and acquired through the FTDI SuperSpeed-FIFO Bridge. The firmware nonce/build/configuration handshake passed before each capture. Lease expiry has passed RTL simulation; deliberately interrupting renewals while transmitting has not been tested on the physical board.

The simulated response is a test of the tools. Subsequent physical testing is documented in [the measured 1 mm wire result](wire-bench-results-2026-09-08.md): 14 RF acquisitions, successful RAM programming and runtime readback, repeatable flat-trim improvement, and final captures with zero clipping. The physical wire result does not establish heart-image improvement.

## Run from the project directory

```powershell
Set-Location C:\Users\Adam\usb3-tester
python tools/bench_build.py doctor
```

This installation has Vivado at `E:\Vivado\2025.2\Vivado\bin\vivado.bat` and the Alchitry V2 CLI available as `alchitry`. The scripts use the uploader's `load` command with `--board AuV2 --ram --bin`. They require exactly one identifiable Au V2 before programming. Unexpected device listings stop the operation and leave `boards.log` for inspection.

The build helpers use a process-only PowerShell execution-policy override. They do not change the machine's execution policy. When run through Codex, Vivado and the WindowsApps uploader alias may require tool execution approval; running the same commands from a normal terminal uses that terminal's permissions.

## Rehearse without a connected probe

```powershell
python tools/bench.py experiment --sim
python tools/bench.py shutdown
```

This captures 16 simulated sweeps, saves the original RF, runs the processing search, validates on two other frames, and writes `report.html`, `experiment.json`, and `selected-settings.json` in a new `bench_runs/experiments/` directory. Individual trials contain annotated PNG images, linear magnitude arrays, metrics, and settings. All simulation recordings and reports identify their source.

## Start a physical wire experiment

Fix the probe face in water looking at the stationary wire, with electronics and connectors dry. Connect both USB3 acquisition and the FPGA programming USB. Keep the existing ±40 V supply setting for the initial experiments. Close other acquisition or uploader applications so the harness owns the USB interfaces. Record the wire diameter, approximate position/depth, and water temperature in the run note. Use the corresponding water sound speed in the saved settings; the current host default is 1496 m/s, which is a model assumption, not a temperature measurement.

Build only when the FPGA source or constraints have changed:

```powershell
python tools/bench_build.py build
```

The command prints its new build directory. It freezes and hashes RTL, constraints, testbench, and build helpers before running Vivado. Builds with failing simulation, setup/hold timing, or severe DRC violations cannot be programmed through this harness. The bitstream and frozen inputs are checked again before programming.

For the already checked build:

```powershell
python tools/bench.py experiment --bench-ready --build bench_runs/builds/20260908T012733Z-41017f --note "Fixed 3 mm wire in water; add depth, temperature and supply observations"
```

`--bench-ready` asserts the physical water/wire setup is ready to transmit. Programming closes the controlled host and waits for its process to exit before resetting the board. After temporary RAM programming, the host verifies firmware identity and selected configuration registers while disarmed, captures a short RF run, disarms, and does the processing comparisons offline.

For a repeat acquisition with known settings:

```powershell
python tools/bench.py experiment --bench-ready --settings "C:\path\known-settings.json" --note "Fixed wire; repeat condition"
```

An idle host remains available after an experiment, with transmission off. Its first-session waveform is locked: currently the B-mode host's 5.2→2.6 MHz, 1 µs chirp, using the existing quantization and dead time. Loading a file with a different waveform fails before configuration is changed. Timing, TGC, trims, receive processing, geometry, and display fields can be restored within their validated ranges. The voltage supply is manual and is recorded as context, never measured or controlled by this software.

After any FPGA source edit, build again and pass that new build directory to `--build`. The existing checked directory remains an immutable baseline.

## Control interface for follow-up experiments

```powershell
python tools/bench.py status
python tools/bench.py configure "C:\path\known-settings.json"
python tools/bench.py stop
python tools/bench.py shutdown
```

`configure` validates the whole file, applies recognized operational fields, and leaves transmission off. Settings restoration never uses a saved `armed` value to start transmission. `status.pulser_requested_armed_now` is the current host request; `status.settings.transmit.armed` can describe the historical acquisition during replay. Neither is a continuously sampled hardware pin.

The low-level interface uses local JSON request/response files with a process identity, request ID, and expiry. It exposes only `status`, `configure`, `capture`, `render`, `stop`, and `shutdown`. No network listener or arbitrary script execution is involved. Logs and responses are retained under `bench_runs/control/`. Use `--control-dir PATH` **before** the subcommand to select another control directory; do not run competing hardware hosts.

Save a request as a JSON file, then run `python tools/bench.py request "C:\path\request.json"`. For example, a fresh recording:

```json
{
  "op": "capture",
  "frames": 16,
  "timeout_s": 20,
  "output": "C:/Users/Adam/usb3-tester/bench_runs/manual-wire-001",
  "note": "Fixed 3 mm wire; condition and physical observations"
}
```

Output directories must be new directories under `bench_runs`. Capture requests accept 1–256 frames and 1–30 seconds. Partial/invalid recordings are retained with a termination reason but do not count as successful acquisition. Each capture starts a new acquisition epoch and drains queued data before accepting sweeps.

A rendering request uses already recorded RF:

```json
{
  "op": "render",
  "session": "C:/Users/Adam/usb3-tester/bench_runs/manual-wire-001/capture.rf.npz",
  "frame": 0,
  "settings": {
    "receive": {"avg_sweeps": 1, "frequency_compounding": false},
    "beamformer": {"cf": 0, "t0_ns": 0},
    "display": {"debug_view": 1, "auto_gain": false, "dyn_db": 80, "curve": 1}
  },
  "box_mm": [-50, 50, 0, 140],
  "search_mm": [-20, 20, 40, 110],
  "output": "C:/Users/Adam/usb3-tester/bench_runs/manual-wire-001-das"
}
```

Replay accepts receive, beamformer, and display changes only. Every trial starts from the recording's saved baseline. Change acquisition timing, gain control, or trims with `configure`, then make a **new** capture. A file containing `{"transmit":{"trim_ns":[...]}}` can restore a specific 48-entry trim table; 48 zero values select flat trims. That does not overwrite the waterfall calibration file.

To run the full processing search on any existing recording, with no USB access:

```powershell
python tools/bench.py experiment --session "C:\path\capture.rf.npz"
```

Shut down a running hardware host first, because an offline experiment starts a simulation/replay host. Refine `--search-mm X0 X1 Z0 Z1` if the wire is outside the default region or another reflector is selected. The report uses a fixed baseline target position for subsequent comparisons.

## What the search measures

The runner searches time-zero offset, receive band, aperture weighting, and matched filtering. Geometry and sound speed remain at the supplied baseline. The scalar objective is provisional and its formula and rejection thresholds are saved in `experiment.json`.

- Scores use **linear ordinary DAS magnitude**, before display compression. Gain is fixed across amplitude images; it cannot change the score.
- The target is searched near the baseline position. Side-clutter gates are 6–25 mm laterally away, within ±5 mm in depth; these measure that declared region, not every artifact in the image. Missing measurement regions cause an error.
- A candidate is rejected if normalized reflector peak falls below half the baseline, clutter p95 worsens by over 3 dB, clutter energy ratio rises by over 50%, frame quality is invalid, or response width cannot be resolved.
- The chosen candidate must improve the declared score on two other frames. Otherwise baseline settings are retained.
- Coherence-weighted images and a coherence map are saved for visual comparison but are excluded from ranking. This keeps suppression of diffuse signal from masquerading as better sensitivity.

The 3 mm wire has finite size. Its measured response width is not point-target resolution. Separate frames test short-term repeatability; another target position/depth is needed to test generalization. A wire in water cannot establish weak-tissue contrast, penetration through the chest, or performance during cardiac motion. Those require further controlled data after the bench issues are understood.

## Firmware and capture provenance

The bench firmware starts disarmed. Opcode `0x1E` enables or renews a transmit lease of 1–5000 ms. The host uses 2000 ms and renews every 250 ms during capture. If the host or USB stops renewing, the FPGA clears arm. Renewal never arms automatically; an expired lease blocks ARM until renewal. Disabling the lease is accepted only while disarmed. Manual hosts remain compatible and can explicitly arm without using a lease.

Opcode `0x1F` sets a fresh query nonce while disarmed; source 3 repeats a 16-word identity/configuration packet. The host checks the nonce, build tag, disarmed state, active lease, window length, receive delay/gap, TGC start/increment, and programmed burst/timing registers before ARM. Raw RF source 2 keeps its existing frame format. A stale programming receipt after a reset to another build does not pass the runtime identity check.

The identity response does **not** read back AFE serial registers, analog voltages, the complete chirp/trim/element memories, ADC-grid fallback counters, or the pulser fault state. Saved settings and command logs describe those requests; they do not prove their physical effect. The RF file includes the successful pre-arm response under `firmware_readback_before_arm`, alongside the programming receipt and RF integrity results.

Programming uses RAM so experiments do not overwrite the existing flash image. A power cycle can reload that older flash firmware, whose original source starts armed. The new RAM firmware cannot change that older image's startup behavior; do not assume its disarmed startup or lease survives a power cycle. Runtime identity is rechecked before each harness capture.

Build manifests preserve exact source hashes, tool paths, timing/DRC results, the binary checksum, and the runtime tag. Capture files preserve decoded pre-filter RF, settings, saved transmit/background references, per-sweep integrity, setup notes, and host source hashes. See [RF format details](rf-debug-harness.md) and [the investigation guide](ultrasound-image-quality-guide.md).

## Next physical session

The first connected run should establish programming and identity, verify timeout/disarm behavior, and collect a stationary wire baseline. Then compare receive processing on that unchanged RF. Follow with fresh recordings for flat versus air-derived trims and selected timing/TGC changes. Use those observations to decide whether the next change belongs in beamforming, acquisition timing, or the analog path.
