# Single-element waveform and noise analyzer

`host/noise_analyzer.py` repeatedly captures the existing `SRC_SEQ` receive
frame for one physical aperture element and produces both a bench-readable
report and a structured evidence bundle for an LLM. It uses the current FT601,
transmit sequencer, mux list, and sample-tag protocol. It does not change the
FPGA or require a new bitstream.

## Start the app

From the project directory:

```powershell
python host/noise_analyzer.py
```

The **Run fault-rich simulation** button exercises the complete analysis and
export path without opening hardware. **Capture hardware** explicitly warns
before it arms the pulser. Only the selected element is put in list slot zero,
the list length is set to one, and the pulser is stopped in cleanup whether the
capture succeeds, fails, or is cancelled.

For a useful hardware-noise baseline, start with:

- 128–512 repeated frames;
- TGC start equal to TGC end (fixed gain);
- the same element, pulse, delay, capture span, probe loading, and supply setup
  for every comparison;
- zero clipped samples and zero transport/tag errors.

Set **Analyze from** to the shallowest depth that matters for imaging (3 cm by
default). The receiver is connected to the transmit line through its limiter,
so saturation and recovery before this gate are expected. The app records that
near-field interval as context but excludes it from the assessment, noise
statistics, spectrum, and alerts.

Depth conversion includes both the 2 µs transmit-trim bias and the selected
element's saved trim. This matters because `tx_sync` opens the timing gate
before the physical HV edge; ignoring that offset makes element-to-element
depth comparisons wrong, especially for a large trim outlier.

The ADC coding checkbox must match the AFE5804 output mode. Leave it off for
offset-binary; turn it on for 12-bit two's-complement.

## What the analyzer separates

The average of repeated, per-frame-DC-removed waveforms is the **repeatable
component**. It includes wanted echoes as well as synchronous transmit
feedthrough, probe ringdown, clock pickup, and other shot-locked artifacts.
The difference between each frame and that average is the **random residual**.
This separation prevents an LLM from calling every early echo or ringdown
feature random electronic noise.

The analysis includes:

- gated total, repeatable, and random RMS in ADC counts and dBFS;
- peak, peak-to-peak, crest factor, rail/near-rail rates, DC drift, kurtosis,
  frame repeatability, and an effective-bit estimate from random noise;
- ADC code span, bit balance, static-bit clues, and LSB activity;
- Welch PSD for the random residual and repeatable waveform;
- strongest lines and integrated noise power in six frequency bands;
- shot-to-shot modulation of frame DC and frame RMS at the single-element pulse
  rate, which can expose low-frequency supply, gain, or mains modulation that
  is too slow to resolve inside one short receive window;
- 6.4 microsecond time gates with random/repeatable level, peak, and impulse
  statistics;
- merged high-noise regions in receive time and equivalent one-way depth;
- FT601 header resyncs, frame-counter gaps, wrong element IDs, and the 4-bit
  per-sample sequence-tag discontinuities.

Equivalent depth is `c * (pulse-to-capture delay + sample time) / 2`. It is
meaningful for echoes. Electrical pickup is still localized accurately in
time, but its displayed depth is not a literal physical source location.

## Evidence bundle

Every run creates a timestamped folder under `host/noise_captures` unless a
different location is selected:

| File | Purpose |
|---|---|
| `capture.npz` | Lossless centred `int16` frames plus settings and transport counters; can be reanalyzed in the app. |
| `analysis.json` | Complete machine-readable metrics, findings, tones, bands, time gates, and suggested comparisons. |
| `report.md` | Compact human-readable interpretation. |
| `overview.svg` | Waveform, time/depth levels, and PSD without a plotting-library dependency. |
| `waveform.csv` | Per-sample mean, random standard deviation, total RMS, time, and equivalent depth. |
| `llm_prompt.txt` | A ready-to-use diagnostic prompt that tells the model how to distinguish the major failure classes. |

Give an LLM `analysis.json` first, along with `report.md` and `overview.svg`.
Attach `waveform.csv` when it needs to inspect a particular time gate. The raw
NPZ is primarily for this app or another Python analysis tool.

## Command-line use

Run a no-hardware analysis and export a demo bundle:

```powershell
python host/noise_analyzer.py --simulate --frames 128
```

Capture one element and exit:

```powershell
python host/noise_analyzer.py --capture --element 23 --frames 256 --depth-cm 14 --analysis-start-cm 3 --tgc 834 834
```

Reanalyze an earlier raw capture without touching hardware:

```powershell
python host/noise_analyzer.py --analyze host/noise_captures/noise_E23_hardware_YYYYMMDD_HHMMSS/capture.npz
```

Use `--output PATH` in a command-line run to select the exact output folder.

## A discriminating capture matrix

Absolute noise alone is difficult to diagnose because it depends on AFE gain,
probe impedance, and loading. A small controlled matrix gives an LLM far more
useful evidence:

1. Selected element, probe face in air, fixed TGC.
2. Same capture with the face acoustically loaded/coupled.
3. Same element at two or three fixed TGC codes.
4. Neighbouring element with every other setting unchanged.
5. Same setup with one power/grounding variable changed at a time.

Compare `random_rms_dbfs`, the repeatable/random power split, strongest line
frequencies, frequency-band powers, and localized regions across those runs.
Transport or sample-tag failures must be fixed first; otherwise lost samples
can masquerade as time-localized analog noise.
