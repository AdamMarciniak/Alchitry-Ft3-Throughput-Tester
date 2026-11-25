"""Offline frequency/aperture comparison on the corrected two-wire gelatin recording."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.fft import fft, ifft
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))
from bench_render import _width
from rf_debug import load_session

SOURCE = ROOT / "bench_runs/two-wire/gelatin-2-wires-trim-comp.rf.npz"
CONTROL = ROOT / "bench_runs/two-wire/search-20261124-v4-corrected/135-band-15"
OUT = Path(__file__).resolve().parent
X = -25 + (np.arange(512) + .5) * 50 / 512
Z = 5 + (np.arange(640) + .5) * 30 / 640


def focused_bands(rf, settings, angles=(16, 18, 22, 26, 30, 36)):
    def smooth(n):
        for prime in (2, 3, 5):
            while n % prime == 0:
                n //= prime
        return n == 1
    nfft = next(n for n in range(rf.shape[1], 2*rf.shape[1]) if smooth(n))
    sample_rate = 40.0  # samples per microsecond
    freq = np.arange(nfft) * sample_rate / nfft
    def ramp(x):
        return (1 - np.cos(np.pi * np.clip(x, 0, 1))) / 2
    band = 2 * ramp((freq - 1.5) / 1.05) * ramp((7.5 - freq) / 1.05)
    # Squared cosine/sine crossfades sum to one for coherent reconstruction.
    # Their square roots are the host's power-complementary masks for RSS.
    transition = np.array([ramp((freq - cut + .18) / .36) for cut in (3.5, 5.5)])
    blend = np.array([1 - transition[0], transition[0] - transition[1], transition[1]])
    filters = np.concatenate([blend, np.sqrt(np.maximum(0, blend))])
    signals = ifft(fft(rf, nfft, axis=-1)[None] * (band * filters)[:, None, :],
                   axis=-1)[:, :, :rf.shape[1]]
    b = settings["beamformer"]
    theta = (np.arange(48) - 23.5) * b["pitch_mm"] / b["R_mm"]
    sums = {a: np.zeros((6, len(Z), len(X)), dtype=np.complex64) for a in angles}
    for i in range(48):
        if i in b["dead"]:
            continue
        dx = X[None, :] - b["R_mm"] * np.sin(theta[i])
        dz = Z[:, None] - b["R_mm"] * (np.cos(theta[i]) - 1)
        dist = np.hypot(dx, dz)
        cos_incidence = (dx * np.sin(theta[i]) + dz * np.cos(theta[i])) / dist
        time = (2000 * dist / b["c_m_s"] + b["t0_ns"] / 1000
                - settings["acquisition"]["dly_us"]) * sample_rate
        k = np.clip(time.astype(int), 0, rf.shape[1] - 2)
        frac = time - k
        y = (signals[:, i, k] * (1 - frac) + signals[:, i, k + 1] * frac)
        for a in angles:
            ok = (cos_incidence >= np.cos(np.deg2rad(a))) & (time >= 0) & (time < rf.shape[1]-1)
            sums[a] += y * ok
    return sums


def measurements(im, locations=((-7.18, 18.62), (7.67, 20.12))):
    wires = []
    for x0, z0 in locations:
        xsel = np.flatnonzero(abs(X - x0) < 1)
        zsel = np.flatnonzero(abs(Z - z0) < .6)
        roi = im[np.ix_(zsel, xsel)]
        row, col = np.unravel_index(roi.argmax(), roi.shape)
        j, i = zsel[row], xsel[col]
        side = (abs(X - x0) > 1.5) & (abs(X - x0) <= 5.5)
        mix = im[np.ix_(abs(Z-z0) < .9, side)]
        wires.append(dict(lateral_mm=_width(im[j], X, i), axial_mm=_width(im[:, i], Z, j),
                          side_p95_db=float(20*np.log10(np.percentile(mix, 95)/im[j,i])),
                          peak=float(im[j,i])))
    gel = []
    for lo, hi in ((11, 15), (27, 31)):
        patch = im[np.ix_((Z >= lo) & (Z < hi), abs(X) < 4)].astype(float)
        centered = patch - patch.mean(axis=1, keepdims=True)
        corr = [1.]
        for lag in range(1, 18):
            left, right = centered[:, :-lag], centered[:, lag:]
            corr.append(np.mean(left * right) / np.sqrt(np.mean(left**2)*np.mean(right**2)))
        crossing = next((i for i in range(1, len(corr)) if corr[i] < .5), None)
        ac_width = None
        if crossing is not None:
            i = crossing
            ac_width = float(2 * (i-1 + (.5-corr[i-1])/(corr[i]-corr[i-1])) * (X[1]-X[0]))
        gel.append(dict(envelope_cv=float(patch.std()/patch.mean()), lateral_acf_fwhm_mm=ac_width))
    return dict(wires=wires, gel=gel)


def main():
    settings = json.loads((CONTROL / "settings.json").read_text())
    session = load_session(SOURCE)
    try:
        assert session.rf.shape == (1, 48, 3208)
        sums = focused_bands(session.rf[0], settings)
        data = dict(rf_sha256=session.metadata["rf_sha256"], controls=settings["beamformer"])
    finally:
        session.close()
    candidates = {"fixed22": (22,22,22), "fixed30": (30,30,30), "fixed36": (36,36,36),
                  "gentle": (26,22,18), "moderate": (30,22,16), "wide_low": (36,22,16)}
    data["trials"] = {}
    for label, angles in candidates.items():
        im = abs(sum(sums[a][k] for k,a in enumerate(angles)))
        data["trials"][label] = measurements(im)
        if label == "fixed22":
            gpu = np.load(CONTROL / "magnitude.npy")
            data["gpu_control_nrms"] = float(np.linalg.norm(im-gpu)/np.linalg.norm(gpu))
            assert data["gpu_control_nrms"] < .01
    rss = np.sqrt(sum(abs(sums[22][k])**2 for k in (3,4,5)))
    data["trials"]["three_band_rss22"] = measurements(rss)
    coherent = abs(sum(sums[22][:3]))
    display = Image.new("RGB", (3*416, 390), "#111820")
    draw = ImageDraw.Draw(display)
    reference = float(np.max(coherent[(Z > 17) & (Z < 21)]))
    for alpha in (0, .25, .5, .75, 1):
        combined = np.sqrt((1-alpha)*coherent**2 + alpha*rss**2)
        data["trials"][f"power_mix_{alpha:.2f}"] = measurements(combined)
        if alpha in (0,.5,1):
            # Equal mm per pixel, same 46 dB window over the wire-depth slab.
            region = combined[np.ix_((Z >= 10) & (Z < 32), abs(X) < 14)]
            grey = np.clip(255 * (1 + 20*np.log10(np.maximum(region/reference,1e-8))/46), 0, 255)
            panel = Image.fromarray(grey.astype(np.uint8)).resize((406,319),Image.Resampling.BILINEAR)
            pos = 416 * int(alpha*2)
            display.paste(panel, (pos+5,50))
            draw.text((pos+8,23), {0:"Broadband DAS",.5:"50% compounded power",1:"100% compounded power"}[alpha],
                      fill="#f0f4f8")
    draw.text((8,373),"Same RF, aperture and grayscale. Each panel is 28 mm wide, 10-32 mm deep.",fill="#dbe6ef")
    display.save(OUT / "frequency-comparison.png")
    single = load_session(ROOT / "bench_runs/phantom-pulse-comparison/one-cycle.rf.npz")
    try:
        metadata = single.metadata["acquired_settings"]
        assert metadata["source"] == "hardware" and not any(metadata["transmit"]["trim_ns"])
        frame = len(single.rf)//2
        assert single.quality[frame]["valid"] and metadata["acquisition"]["fs_hz"] == 40000000
        settings["acquisition"] = metadata["acquisition"]
        channels = focused_bands(single.rf[frame], settings, angles=(22,))[22]
        control = abs(channels[:3].sum(axis=0))**2
        rss_power = (abs(channels[3:])**2).sum(axis=0)
        holdout = {str(a): measurements(np.sqrt((1-a)*control + a*rss_power), [(2.39,16.16)])
                   for a in (0,.25,1)}
        data["independent_one_cycle"] = dict(rf_sha256=single.metadata["rf_sha256"], frame=frame,
                                              path="bench_runs/phantom-pulse-comparison/one-cycle.rf.npz",
                                              trials=holdout)
        print("independent capture", json.dumps(holdout))
    finally:
        single.close()
    (OUT / "frequency-aperture.json").write_text(json.dumps(data, indent=2))
    for key, val in data["trials"].items():
        print(key, [(round(w["lateral_mm"],3),round(w["axial_mm"],3),round(w["side_p95_db"],1)) for w in val["wires"]],
              [(round(g["envelope_cv"],3),round(g["lateral_acf_fwhm_mm"],3)) for g in val["gel"]])
    print("GPU relative RMS difference", data["gpu_control_nrms"])


if __name__ == "__main__":
    main()
