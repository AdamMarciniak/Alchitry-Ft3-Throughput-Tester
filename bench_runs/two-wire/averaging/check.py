"""Compare the host's RF boxcar averages on a stationary 48-sweep one-cycle recording."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.fft import fft, ifft

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / "host"))
from bench_render import _width
from rf_debug import load_session

record = ROOT / "bench_runs/phantom-pulse-comparison/one-cycle.rf.npz"
preset = json.loads((ROOT / "host/presets/gelatin-two-wire-best.json").read_text())
b = preset["beamformer"]
x = np.arange(-5, 5.01, .05)
z = np.r_[np.arange(14.5, 18.01, .05), np.arange(26, 29.01, .05)]
gel = np.ix_(z >= 26, abs(x) <= 4)
wire = (abs(z[:, None] - 16.2) <= 1.2) & (abs(x[None, :] - 2.3) <= 1.3)


def db(ratio):
    return float(20 * np.log10(ratio))


def channel_lookups(acquisition, sample_count):
    paths = []
    for element in sorted(set(range(48)) - set(b["dead"])):
        angle = (element - 23.5) * b["pitch_mm"] / b["R_mm"]
        dx = x - b["R_mm"] * np.sin(angle)
        dz = z[:, None] - b["R_mm"] * (np.cos(angle) - 1)
        distance = np.hypot(dx, dz)
        accept = (dx * np.sin(angle) + dz * np.cos(angle)) >= distance * np.cos(np.deg2rad(b["accept_deg"]))
        index = (2000 * distance / b["c_m_s"] + b["t0_ns"] / 1000 - acquisition["dly_us"]) * acquisition["fs_hz"] / 1e6
        assert index.min() >= 0 and index.max() < sample_count - 1
        integer = index.astype(int)
        paths.append((element, integer, (index - integer).astype(np.float32), accept))
    return paths


def render(frame, paths, count, mask):
    traces = ifft(fft(frame, n=len(mask), axis=-1) * mask, axis=-1)
    total = np.zeros(count.shape, dtype=np.complex64)
    power = np.zeros(count.shape, dtype=np.float32)
    for i, k, frac, accept in paths:
        sample = (traces[i, k] * (1-frac) + traces[i, k+1] * frac) * accept
        total += sample
        power += abs(sample)**2
    envelope = abs(total)
    return envelope * (envelope**2 / np.maximum(count*power, 1e-20))**b["cf"]


session = load_session(record)
try:
    a = session.metadata["acquired_settings"]
    assert all(q["valid"] for q in session.quality) and len(session.rf) == 48
    assert a["transmit"]["shot_method"] == 0 and not any(a["transmit"]["trim_ns"])
    assert a["acquisition"]["fs_hz"] == 40000000 and session.rf.shape[-1] == 3208
    paths = channel_lookups(a["acquisition"], session.rf.shape[-1])
    count = sum(p[3].astype(np.float32) for p in paths)
    # Host selects the smallest 5-smooth FFT size >= 3208.
    f = np.arange(3240) * 40 / 3240
    ramp = lambda v: (1 - np.cos(np.pi * np.clip(v, 0, 1))) / 2
    mask = (2 * ramp((f-1.5)/1.05) * ramp((7.5-f)/1.05)).astype(np.float32)
    results = {}
    for n in (1, 2, 4, 8):
        widths, peak, texture, repeat = [], [], [], []
        for start in range(0, 48, 16):
            # Compare equal-size groups with a fixed eight-sweep separation.
            for j in range(start, start+8, n):
                pair = []
                for k in (j, j+8):
                    frame = session.rf[k:k+n].mean(axis=0, dtype=np.float32)
                    im = render(frame, paths, count, mask)
                    row, col = np.unravel_index(np.argmax(np.where(wire, im, -1)), im.shape)
                    widths.append(_width(im[row], x, col))
                    peak.append(float(im[row, col]))
                    patch = im[gel]
                    pair.append(patch)
                    texture.append(float(np.median(patch)))
                repeat.append(np.mean((pair[0] - pair[1])**2))
        results[n] = dict(lateral_mm=float(np.median(widths)), peak=float(np.median(peak)),
                          gel_median=float(np.median(texture)), gel_pair_rms=float(np.sqrt(np.mean(repeat))),
                          group_count=len(widths))
    for item in results.values():
        item["gel_pair_rms_change_db"] = db(item["gel_pair_rms"]/results[1]["gel_pair_rms"])
        item["gel_median_change_db"] = db(item["gel_median"]/results[1]["gel_median"])
    out = dict(capture=str(record), rf_sha256=session.metadata["rf_sha256"], preset=preset["beamformer"],
               gel_region_mm=[-4,4,26,29], description="Coherence-weighted envelope, images compared at the same eight-sweep separation. Temporal changes include motion and phase variation as well as noise.", results=results)
    (OUT / "results.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(results,indent=2))
finally:
    session.close()
