# Longer-chirp axial smearing: compression audit

Vertical smearing can often be reduced after acquisition **if signed raw RF and the correct waveform reference were saved**. The relevant operation is pulse compression before envelope detection. The TFM host already implements it under **pulse comp**, independently of the chirp control. All three earlier heart presets had it off. The user does not recall whether it was enabled during the longer-chirp experiment, and no new long-chirp RF file was found among the supplied recordings.

## What the code does

`PulserCtl.tx_waveform()` constructs a sampled reference from the commanded quantized switching edges, including return-to-zero gaps. The host uses the recorded reference during RF-file replay and otherwise refreshes it when pulse settings change. `analytic()` multiplies the RF spectrum by the conjugate reference spectrum, with reference-energy normalization and the analytic/bandpass mask. FFT padding prevents circular correlation from wrapping the window ends. Processing occurs on signed RF before envelope detection and beamforming.

The source uses the correct correlation direction. The current RTL prefetches the next chirp-table width before loading it; inspection did not find a repeated-first-entry error. This is a source/code-path check, not readback of the bitstream used for the user's latest experiment.

The reference describes the requested electrical drive, not the measured probe/pulser/mux/protection/AFE response. A bandpass does not calibrate that response's phase or amplitude. Pulse compression can therefore work mathematically and still leave broad lobes or axial sidelobes in real recordings.

## Independent synthetic echo check

The audit synthesized +/-1/0 excitation at100 MHz from the chirp-table widths, applied an assumed causal analog bandpass, resampled to40 MSPS, and sent the RF through the **production host decoder in simulation**. No physical hardware was opened. The waveform swept5.2 to2.6 MHz; receive processing used2–5 MHz. There was no noise, tissue motion or nonlinear response in this model.

| Requested chirp | Uncompressed width, assumed2–5 MHz analog response | Compressed width |
|---|---:|---:|
| 1 microsecond | 0.652 mm | 0.513 mm |
| 2 microseconds | 1.244 mm | 0.444 mm |
| 4 microseconds | 2.443 mm | 0.446 mm |
| 8 microseconds | 4.903 mm | 0.451 mm |
| 16 microseconds | 9.930 mm | 0.445 mm |

Widths are contiguous -6.02 dB amplitude widths at assumed1540 m/s, with interpolated crossings. These are simulated algorithm results, **not measured probe resolution or SNR gains**. With an assumed narrower2.8–3.6 MHz analog response, the compressed width stayed roughly0.95–1.09 mm: increasing chirp length cannot recover bandwidth that the signal path does not pass. A deliberately incorrect1-microsecond reference for the16-microsecond narrow-band echo left a3.60 mm width, showing that reference mismatch can also produce smearing.

The results support normal operation of the basic decoder under the model. They do not establish what happened in the unsaved longer-chirp experiment. The existing short-chirp heart RF cannot be turned into a measurement of longer excitation.

## Practical next comparison

1. Open a saved long-chirp RF recording and freeze the same frame. Keep band, gain, dynamic range, CF and averaging fixed.
2. Toggle **pulse comp** off/on. This changes only receive processing during replay. Judge the axial width and trailing/leading sidelobes of an isolated echo, not just brightness.
3. If smearing persists with compression on, use an isolated wire-in-water echo with the same chirp to characterize the received waveform and test a measured-template, sidelobe-controlled or regularized inverse filter. The existing1 mm wire is a finite target, so its response is not a pure point-spread-function measurement.
4. Check clipping and whether the full echo lies inside the recorded window. A decoder cannot reconstruct the missing beginning/end of a pulse that was blanked or never sampled. If the burst approaches or exceeds the pulse-to-receive delay, acquisition timing also needs review on the bench.

Windowed/mismatched filters can trade some peak SNR or main-lobe width for lower range sidelobes; regularized inverse filters can help compensate a measured response without unbounded amplification at spectral nulls. These need evaluation on the actual RF rather than default sharpening. [Primary pulse-compression study](https://pubmed.ncbi.nlm.nih.gov/15801308/), [primary Wiener-filter study](https://pubmed.ncbi.nlm.nih.gov/17935865/).

## Host clarification

The image/status summary now records **burst duration** and **pulse-comp on/off**. The pulse-comp tooltip explains that it is separate from chirp, works during offline replay, and uses a commanded rather than acoustically measured reference. Compression behavior, transmit settings and presets were not changed. No FPGA programming occurred.

Reproducible audit: `python bench_runs/chirp-compression-audit-20260909/audit.py`. The folder contains the declared model, JSON width measurements and envelope profiles. No source RF was modified.
