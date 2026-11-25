"""Offline DAX pilot on the measured two-wire phantom. Run this file with Python."""
import json
import argparse
import sys
import zipfile
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT / "host"))
from bench_render import _width

source = ROOT / "bench_runs/two-wire/gelatin-2-wires-trim-comp.rf.npz"
sweep = ROOT / "bench_runs/two-wire/search-20261124-v4-corrected"
cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("--single-wire", action="store_true", help="Check the independent one-cycle flat-trim acquisition.")
cli.add_argument("--frame", type=int, default=0)
args = cli.parse_args()
if args.single_wire:
    source = ROOT / "bench_runs/phantom-pulse-comparison/one-cycle.rf.npz"
with np.load(source) as recording:
    rf = recording["rf"][args.frame]
with zipfile.ZipFile(source) as recording:
    acquired = json.loads(recording.read("metadata.json"))["acquired_settings"]
    quality = json.loads(recording.read("quality.json"))
assert quality[args.frame]["valid"] and acquired["source"] == "hardware"
preset = json.loads((sweep / "selected-settings.json").read_text())
bf = preset["beamformer"]
rx = preset["receive"]
fs = acquired["acquisition"]["fs_hz"]
# The production FFT length is the smallest 5-smooth number >= the window size.
def smooth(n):
    for p in (2,3,5):
        while n%p == 0:
            n //= p
    return n == 1
nfft = next(n for n in range(rf.shape[1],2*rf.shape[1]) if smooth(n))
freq = np.arange(nfft) * fs / nfft / 1e6
lo, hi = rx["band_lo_mhz"], rx["band_hi_mhz"]
transition = 0.35 * (hi - lo) / 2
def ramp(v):
    return (1 - np.cos(np.pi * np.clip(v, 0, 1))) / 2
mask = 2 * ramp((freq-lo)/transition) * ramp((hi-freq)/transition)
analytic = np.fft.ifft(np.fft.fft(rf, n=nfft, axis=-1) * mask, axis=-1)

# Match saved 512x640 pixel centres, with 3x axial oversampling for RF correlation.
x = -25 + (np.arange(512) + 0.5) * 50/512
z = 5 + (np.arange(1920) + 0.5) * 30/1920
xx, zz = np.meshgrid(x, z, sparse=True)
shape = (len(z), len(x))
total = np.zeros(shape, dtype=complex)
halves = {k: np.zeros_like(total) for k in (2, 4)}
hann = np.zeros_like(total)
power = np.zeros(shape)
counts = np.zeros(shape)
for i in range(48):
    if i in bf["dead"]:
        continue
    theta = (i - 23.5) * bf["pitch_mm"] / bf["R_mm"]
    dx = xx - bf["R_mm"] * np.sin(theta)
    dz = zz - bf["R_mm"] * (np.cos(theta)-1)
    dist = np.hypot(dx, dz)
    accept = (dx*np.sin(theta) + dz*np.cos(theta)) / dist >= np.cos(np.radians(bf["accept_deg"]))
    idx = (2e-3 * dist / bf["c_m_s"] + bf["t0_ns"]*1e-9 - acquired["acquisition"]["dly_us"]*1e-6) * fs
    channel = np.interp(idx, np.arange(nfft), analytic[i]) * accept
    total += channel
    hann += np.hanning(48)[i] * channel
    counts += accept
    power += abs(channel)**2
    for block, half in halves.items():
        if (i // block) % 2 == 0:
            half += channel

das = abs(total)
cf = das * (das**2 / np.maximum(counts * power, 1e-18))**bf["cf"]
images = {"DAS":das, "CF0.15":cf}
# DAX alternating apertures, applied across transmit/receive pairs in a
# sequential monostatic aperture. Compute real RF zero-lag normalized
# correlation over 23 z samples (0.359 mm), then weight the full sum.
def mean_axial(data):
    return uniform_filter1d(data, size=23, axis=0, mode="nearest")
pairs = {f"DAX{block}":(half, total-half) for block,half in halves.items()}
pairs["Uniform-Hann"] = total, hann
for name,(one,two) in pairs.items():
    a, b = one.real, two.real
    corr = mean_axial(a*b) / np.maximum(np.sqrt(np.maximum(mean_axial(a*a), 0) * np.maximum(mean_axial(b*b), 0)), 1e-18)
    weight = np.clip(corr, 0.001, 1)
    images[name] = das * weight
    if name == "DAX4":
        images["DAX4-soft"] = das * (0.55 + 0.45*weight)

def db(ratio):
    return 20*np.log10(np.maximum(ratio, 1e-12))

regions = [(-7.18, 18.62), (7.67, 20.12)]
if args.single_wire:
    # Saved independent wire search around x=1.7, z=18 mm; allow the new t0
    # and sound speed to shift its apparent depth. Lock ROIs on the DAS peak.
    gate = (abs(xx-1.7)<2.0) & (abs(zz-17.5)<3.0)
    row,col = np.unravel_index(np.argmax(np.where(gate,das,-1)), shape)
    regions = [(x[col],z[row])]
def measure(mag):
    metrics = {}
    for name, (cx, cz) in zip(("wire",) if args.single_wire else ("left","right"),regions):
        core = (abs(xx-cx)<=1) & (abs(zz-cz)<=0.6)
        r,c = np.unravel_index(np.argmax(np.where(core, mag, -1)), shape)
        wings = (abs(xx-cx)>=1.4) & (abs(xx-cx)<=5.5) & (abs(zz-cz)<=0.85)
        metrics[name] = {"peak":mag[r,c], "fwhm_mm":_width(mag[r],x,c), "wings_p95_db":db(np.percentile(mag[wings],95)/mag[r,c])}
    for name,zrange in (("near",(13,16)), ("far",(26,29))):
        region = (abs(xx)<=4) & (zz>=zrange[0]) & (zz<=zrange[1])
        vals = mag[region]
        metrics[name] = {"median_db_vs_DAS":db(np.median(vals)/np.median(das[region])), "contrast_sd_over_mean":np.std(vals)/np.mean(vals)}
    return metrics

results = {name:measure(img) for name,img in images.items()}
if not args.single_wire:
    gpu = np.load(sweep / "135-band-15/magnitude.npy")
    results["production_DAS_pixel_similarity"] = np.corrcoef(gpu.ravel(),das[1::3].ravel())[0,1]
results["source"] = str(source)
results["frame"] = args.frame
results["anchors_mm"] = regions
prefix = f"holdout-{args.frame}-" if args.single_wire else ""
(OUT/f"{prefix}metrics.json").write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))

# Equal intensity mapping and physical aspect ratio throughout.
canvas = Image.new("RGB",(2*520,3*250), "#18202a")
draw = ImageDraw.Draw(canvas)
for i,(name,img) in enumerate(images.items()):
    render = np.clip((db(img/das.max())+55)/55,0,1)
    crop = render[(z>=13)&(z<=30)][:,(x>=-15)&(x<=15)]
    frame = Image.fromarray(np.uint8(crop*255)).resize((380,215),Image.Resampling.BILINEAR)
    x0,y0 = (i%2)*520+26,(i//2)*250
    canvas.paste(frame,(x0,y0+25))
    draw.text((x0,y0+5),f"{name}   30 x 17 mm   55 dB", fill="white")
canvas.save(OUT/f"{prefix}comparison.png")
