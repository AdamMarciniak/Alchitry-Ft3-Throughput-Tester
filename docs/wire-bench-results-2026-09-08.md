# Measured result: 1 mm wire in approximately 21 °C water

The unattended bench run completed 14 physical RF acquisitions and more than 100 image reconstructions, including the generic processing searches. The probe and wire remained fixed as reported by the owner; the wire appeared around 51 mm deep. The uploaded RAM firmware was checked build `8841d2b2`. Its runtime identity and selected configuration registers were verified before each capture.

The chosen settings are in [wire-21c-1mm-best.json](../host/presets/wire-21c-1mm-best.json). An [ordinary-DAS reference](../host/presets/wire-21c-1mm-das.json) uses the same acquisition settings with coherence weighting bypassed. The [full illustrated report](../bench_runs/wire-21c-1mm/report.html), [final RF recording](../bench_runs/wire-21c-1mm/validation-flat-b/capture.rf.npz), and [machine-readable results](../bench_runs/wire-21c-1mm/study-summary.json) are saved locally. `bench_runs` is intentionally excluded from Git because it contains large recordings and generated images.

## Changes that mattered

| Change | Measured result |
| --- | --- |
| Damp gap 50 → 300 µs | Removed skipped element acquisitions. The initial 32 saved sweeps were incomplete; every subsequent acquisition condition passed integrity checks. |
| Air-derived → flat transmit trims | Ordinary-DAS wire peak increased **6.6 dB** in the controlled final comparison. Broad arc-region p99 improved from approximately **−12 to −21 dB** relative to the wire, without coherence weighting. |
| Constant TGC 1600 | Preserved wire signal while avoiding saturation of the container-bottom echo. Higher tested gains clipped the bottom; lower gains reduced useful wire amplitude. |
| Receive start 15 µs | Excluded the clipped early transient. Final recordings had **zero clipped samples**. This excludes ranges shallower than approximately 11 mm. A later 25 µs start gave no material wire benefit. |
| Reconstruction mask for quiet channels | Excluded IDs **2, 3, 6, 7, 18, 19, 22, 23, 25, 46**, whose band-limited echoes were negligible at both the wire and bottom. All 48 IDs remain acquired. This is not a diagnosis of physically broken elements. |
| Band 2–5 MHz, Hann aperture, CF exponent 2, four-sweep averaging | Suppressed most wire-associated arcs while retaining about **72%** of the ordinary-DAS wire peak on the same RF. |
| Fixed 45 dB display range, +40 dB display gain, linear gray curve | Chosen display for the wire. Display settings do not enter the linear magnitude measurements. |

Sound speed was modeled as approximately 1485 m/s for the reported temperature using the [NPL water sound-speed reference](https://resource.npl.co.uk/acoustics/techguides/soundpurewater/underlying-phys.html). Geometry remained at the measured radius 67.52 mm and pitch 0.3375 mm. The existing 5.2→2.6 MHz, 1 µs chirp and ±40 V supply setting were retained; the supply was not electronically measured.

## Repeatability and interpretation

The final A/B/A sequence used flat trims, restored air-derived trims, then returned to flat. Each condition captured 32 complete frames with zero clipping. Four frames per recording were compared with the same band, aperture, channel mask, gain and display reference.

With flat trims and the chosen coherence setting, broad arc-region p99 stayed around **−50 to −51 dB** relative to the wire in both fresh flat-trim recordings. The measurement covers a ±4 mm shell at the wire's range from the measured array curvature centre, across the full ±50 mm image width, excluding ±5 mm laterally around the wire. It is a defined image-domain measurement, not an independent electronic SNR or acoustic-power measurement.

A small point-like off-wire feature remains near lateral +13.6 mm, depth 53.3 mm. It may be a bubble or another reflector; its physical identity was not established. The container-bottom echo remains visible in the whole-scene image. These were not erased or spatially masked. Nonlinear coherence weighting narrows the displayed wire response; its apparent width is not evidence of submillimetre resolving power.

This is the best wire display among the tested settings. It is **not a cardiac preset**: strong coherence weighting and the narrower display range suppress diffuse tissue. The flat-trim and acquisition-integrity improvements warrant further investigation, but the water experiment does not establish tissue contrast or penetration through the chest.

## Resume from the saved settings

In the TFM host, use **load settings…** and select the chosen preset. Loading leaves transmission off. For an already running bench host:

```powershell
python tools/bench.py configure host/presets/wire-21c-1mm-best.json
```

Use the [automated bench guide](autonomous-wire-bench.md) to start the controlled host or program the checked build again. Programming was temporary RAM; a power cycle can restore the older flash firmware and its original startup behavior. The harness checks runtime identity before capture.

The final preset was loaded, transmission was stopped, and both controlled hosts were shut down after the study. The original waterfall calibration file was preserved.
