# RF debugging and repeatable bench tests

The debugging controls are in `host/tfm_gl_host.py`. They work with the existing FPGA stream; the manual RF workflow does not require a new bitstream. No hardware acquisition was performed while implementing it. The separate [automated wire bench](autonomous-wire-bench.md) adds checked FPGA builds, temporary programming, controlled capture, and image experiments; its unattended hardware mode requires the new lease/identity firmware.

## Try the workflow without powering anything

From `C:\Users\Adam\usb3-tester`, run:

```powershell
python host/tfm_gl_host.py sim
```

1. Let the synthetic phantom run for a few seconds.
2. Enter a note in the new context field, for example `Simulation; trying save/replay`.
3. Click **save RF…**. Choose **Current frame**, **Marked range**, or **Entire frozen cine**, then choose a filename.
4. The host freezes the cine and turns PULSER RUN off. Saving writes a `.rf.npz` recording and a `.report.json` alongside it. Keep the RF file: the report cannot reconstruct the data.
5. Click **open RF…**, select that recording, and scrub/play the saved frames. You can change receive filters, averaging, geometry, sound speed, apodization, coherence, and display controls on the same RF.
6. Switch between **weighted image**, **ordinary DAS**, and **coherence map**. Ordinary DAS bypasses coherence weighting. The coherence map is linear black=0, white=1 and bypasses gain/log compression. Both diagnostic views use the full receive band, temporarily bypassing frequency compounding.
7. Click **save settings** to keep this processing configuration. It writes a timestamped JSON and, when a rendered image is available, a matching PNG in `host/settings/`. The context field supplies the note; Shift-click can override it.

You can also open a recording directly, without opening a USB device:

```powershell
python host/tfm_gl_host.py --replay "C:\path\wire-test.rf.npz"
```

An invalid replay file stays in simulation; it does not fall through to opening hardware. Replay uses the transmit reference stored in the recording. It never uploads that recording's pulser settings to hardware. **New live run** returns to this process's original source: a process started with `sim` or `--replay` stays in simulation. Restart normally to connect to hardware.

## The first real bench recording

1. Prepare the stationary wire-in-water experiment described in [the image-quality guide](ultrasound-image-quality-guide.md). The existing 3 mm wire is suitable for comparing arcs, but is not a point target for resolution measurements.
2. Start `python host/tfm_gl_host.py`. **PULSER RUN now starts off.** Confirm the window says hardware rather than simulation; the host still falls back to simulation if USB cannot open.
3. Use **load settings…** to restore an existing host settings JSON, or set up the acquisition manually. Loading validates the whole file before applying it and leaves PULSER RUN off. Old `host/settings/*.json` snapshots are supported; missing newer fields keep their current values. Unrelated report JSON files are rejected.
4. Enter the target, distance, water temperature, supply setting, and anything changed since the last run in the context field. The recording also embeds the historical owner-reported hardware profile from [ultrasound-debug-setup.json](ultrasound-debug-setup.json); edit that file after circuit changes. Its contents are context, not live measurements.
5. Keep **avg = 1**, background subtraction and de-jitter off for the first recording. Use the guide's controlled display comparison. Do not change transmission while comparing processing on one recording.
6. Check **PULSER RUN**, allow the status to pass `settling queued data`, and collect a few seconds. Starting transmission or changing acquisition settings clears the old cine and starts a new run. If you want the old run, save it first.
7. Click **save RF…** and save the entire short cine or a marked range. This freezes and disarms transmission. Wait for `Saved RF + report` before closing.
8. Save three settings/PNG pairs while reviewing the same frame: ordinary DAS, weighted image at the comparison coherence value, and the coherence map. Keep display gain and dynamic range fixed for the two amplitude images. The CF map is a different quantity and has its own 0–1 scale.

**FREEZE alone still only freezes review.** You can uncheck PULSER RUN after freezing; frozen controls allow stopping transmission but prevent rearming until you resume. **Save RF** stops transmission automatically. Acquisition controls are locked during review because changing them cannot change recorded RF.

For the flat-trim experiment, choose **new live run**, then **use flat trim** and acquire new RF. **Restore loaded trim** returns the table held in memory before that toggle. Neither button overwrites the waterfall calibration file. Record the two runs separately; air-derived trims and flat trims are different acquisition conditions. This toggle does not perform acoustic calibration.

## What is preserved

| Item | Contents |
| --- | --- |
| RF | Every saved sweep, shape `(frames, 48, samples)`, signed 16-bit ADC counts after decoding the ADC offset/coding, before averaging, background subtraction, filtering, Hilbert transform, or beamforming |
| Acquisition | Sample rate, sample/window count, pulse-to-receive delay, gap, requested analog TGC, complete burst/chirp settings, element selection, and all 48 transmit trims |
| Reconstruction | Geometry, sound speed, dead-element mask, receive filters, averaging, matched filter, coherence/apodization, display settings, and diagnostic view |
| References | The host's quantized transmit reference waveform, plus the captured background array when present |
| Integrity | Per-frame valid/missing/bad element lists, element frame counters, transport-counter snapshots, and a SHA-256 checksum of decoded RF |
| Context | Free-text test note, historical hardware profile, bounded host command log, source-file hashes, original frame indices, and timestamps |

Raw sample tags and complete USB packets are **not** preserved. Frame quality retains their checked discontinuities. Timestamps describe host receipt, not the exact firing time of each element. Source hashes identify files on disk; they do not identify the programmed FPGA bitstream or prove which registers hardware accepted. Manual captures mark those readbacks as unavailable. Automated bench captures additionally attach their checked programming receipt and a pre-arm runtime identity/configuration response; the automation guide lists what it does and does not verify.

A current-frame or marked-range export includes up to `avg - 1` preceding RF frames needed to reproduce the first selected averaged frame. Replay initially seeks to that selected frame. At the oldest edge of a cine, unavailable earlier frames cannot be recovered. Increase averaging later only when the saved history supports it.

Settings JSON alone does not contain RF or a background reference. Loading it for a new run disables background subtraction/de-jitter until a new reference is captured. RF sessions do contain that reference. Annotation/caliper objects and M-mode history are not restored as interactive objects by settings loading; their existing snapshot descriptions are informational.

## Inspect a recording later

The GUI's **RF report…** analyzes the frozen recording without another acquisition. For analysis without Qt or USB:

```powershell
python host/rf_debug.py "C:\path\wire-test.rf.npz" --report "C:\path\wire-report.json"
```

The report measures per-element peak, RMS/dBFS, full-window clipping fraction, RMS in four equal time gates, and variation across repeated RF frames. It examines at most 64 evenly selected frames and lists the exact indices. Elements with invalid data are excluded from their measurements; check `frames_measured` before interpreting a low reading. A one-frame capture cannot estimate variation across shots.

The temporal residual includes motion, timing variation, and electronics. It is **not** an electronic-noise or SNR measurement by itself. An apparently quiet or weak element is not automatically open. For an acquisition with persistently damaged sweeps, the existing display fallback still publishes occasional degraded frames; missing rows are now zero-filled and those frames are explicitly marked invalid in the file/report.

For custom analysis, the portable loader validates and memory-maps RF:

```python
import sys
sys.path.insert(0, r"C:\Users\Adam\usb3-tester\host")
from rf_debug import load_session

s = load_session(r"C:\path\wire-test.rf.npz")
try:
    rf = s.rf                    # int16, [frame, element, sample]
    one_trace = rf[0, 12].copy() # copy anything needed after close()
    settings = s.metadata["acquired_settings"]
    quality = s.quality[0]
finally:
    s.close()
```

The archive is ZIP with ordinary NPY arrays and JSON, without pickle. Saving streams frames instead of stacking a second full cine in RAM. Ordinary recordings now open through a read-only memory map of the RF inside the archive, without making a second large disk copy. The loader still checks the complete RF SHA-256 and ZIP CRC. Compressed or nonstandard-layout archives retain the temporary extraction fallback and need free space approximately equal to the recording size. The GUI can pause while a large file is validated. Close the file by opening another one, choosing new live run, or closing the host. On Windows, close an open recording before replacing that source file, or save under a different name.

## Acquisition boundaries and remaining instrumentation

The host clears partial sweeps and discards the eight queued 1 MiB USB transfers plus a 256 KiB device-buffer allowance after acquisition changes. This is a conservative host boundary, **not a firmware acknowledgement**. No image should be collected into the new cine until that drain completes; with transmission off, it can remain waiting. Settings changes can discard unsaved cine, so save before changing the acquisition.

The RF frame protocol supplies element IDs, frame counters and 4-bit sample continuity tags, enough for these recording checks. The automated bench extension now adds a separate disarmed build-identity/configuration query and a transmit lease. ADC-grid fallback counters and measured analog voltages remain unavailable. The manual save/replay controls do not perform that query, and no physical FPGA programming was performed during implementation.

Software validation: portable archive/settings tests, real-host Qt controls/parser tests in simulation, and numerical OpenGL checks of DAS/CF weighting and the coherence-map display. The new live USB timeout/restart handling still needs a connected-device bench check. No image-quality improvement is claimed until the controlled recordings are compared.
