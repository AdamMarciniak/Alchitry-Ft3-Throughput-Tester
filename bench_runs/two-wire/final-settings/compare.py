"""Saved RF only. Compare the original focus and corrected two-wire settings."""
import copy
import itertools
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT/"host"))
sys.argv = [sys.argv[0], "sim"]
import tfm_gl_host as h
from bench_render import Renderer, _width

assert not h.HW
h.stats["alive"] = False
h.hil_ev.set()
h.reader_thread.join(timeout=4)
h.hilbert_thread.join(timeout=4)
assert not h.reader_thread.is_alive() and not h.hilbert_thread.is_alive()

box = [-16,16,10,32]
width, height = 768,528
x = box[0]+(np.arange(width)+.5)*(box[1]-box[0])/width
z = box[2]+(np.arange(height)+.5)*(box[3]-box[2])/height
xx, zz = np.meshgrid(x,z,sparse=True)
def db(val):
    return 20*np.log10(np.maximum(np.asarray(val,dtype=float),1e-20))
renderer = Renderer(h)
targets = [(-7.18,18.62),(7.67,20.12)]

def analytic(path, settings):
    beam = settings["beamformer"]
    rx = settings["receive"]
    h.geom.update(R_mm=beam["R_mm"], pitch_mm=beam["pitch_mm"])
    h.rebuild_geometry()
    h.set_dead("25,46")
    h.flip["on"] = False
    h.pulser.shot_method = 0
    h.pulser.n_elem = 48
    h.pulser.single_elem = None
    h.state.update(accept=beam["accept_deg"],apod=beam["apod"], cf=beam["cf"],
                   c=beam["c_m_s"],t0_ns=beam["t0_ns"],dly_us=settings["acquisition"]["dly_us"],
                   band_on=True,band_f0=rx["band_f0_mhz"],band_bw=rx["band_bw_mhz"],
                   mf=False,jit=False,freq_comp=False,debug_view=0,auto=False, curve=.9, dyn=66,gain=25)
    with np.load(path) as rec:
        rf = rec["rf"][0]
    return h.prepare_analytic(rf,rf.shape[1],live=False)

def measure(mag, anchors):
    result = {"wires":[]}
    for cx,cz in anchors:
        core = (abs(xx-cx)<1.1)&(abs(zz-cz)<0.75)
        row,col = np.unravel_index(np.argmax(np.where(core,mag,-1)),mag.shape)
        wings = (abs(xx-cx)>=1.4)&(abs(xx-cx)<=5.5)&(abs(zz-cz)<=.85)
        result["wires"].append({"xz_mm":[x[col],z[row]],"lat_mm":_width(mag[row],x,col),
            "ax_mm":_width(mag[:,col],z,row),"peak_db":db(mag[row,col]),
            "flank_p95_rel_db":db(np.percentile(mag[wings],95)/mag[row,col])})
    result["gel_median_db"] = [db(np.median(mag[(abs(xx)<=4)&(zz>=a)&(zz<=b)]))
                               for a,b in ((13,16),(26,29))]
    return result

def render(an,accept,apod,cf):
    h.state.update(accept=accept,apod=apod,cf=cf)
    mag, _ = renderer.render(an,box,width,height)
    return mag

raw = ROOT/"gelatin-2-wires.rf.npz"
with zipfile.ZipFile(raw) as archive:
    original = json.loads(archive.read("metadata.json"))["review_settings"]
raw_an = analytic(raw, original)
b = original["beamformer"]
before = render(raw_an,b["accept_deg"],b["apod"],b["cf"])
run = ROOT/"bench_runs/two-wire/search-20261124-v4-corrected"
corrected = ROOT/"bench_runs/two-wire/gelatin-2-wires-trim-comp.rf.npz"
settings = json.loads((run/"selected-settings.json").read_text())
an = analytic(corrected,settings)
balanced = render(an,22,0,.15)
baseline = measure(balanced,targets)
candidates = []
for accept,apod,cf in itertools.product((18,22,26,30,36), (0,.20,.45), (0,.15,.35,.5,.6)):
    candidate = measure(render(an,accept,apod,cf), targets)
    candidate.update(accept=accept,apod=apod,cf=cf)
    delta_gel = np.asarray(candidate["gel_median_db"])-baseline["gel_median_db"]
    permitted = (delta_gel.min() >= -10 and all(
        wire["peak_db"] >= ref["peak_db"]-2 and
        np.linalg.norm(np.array(wire["xz_mm"])-ref["xz_mm"])<=.30 and
        wire["flank_p95_rel_db"]<=ref["flank_p95_rel_db"]-2
        for wire,ref in zip(candidate["wires"],baseline["wires"])))
    candidate["eligible"] = bool(permitted)
    candidate["max_relative_width"] = max(w["lat_mm"]/r["lat_mm"]
                                          for w,r in zip(candidate["wires"],baseline["wires"]))
    candidates.append(candidate)
best = min((t for t in candidates if t["eligible"]),key=lambda t:t["max_relative_width"])
detail = render(an,best["accept"],best["apod"],best["cf"])
renderer.close()
def save_preset(name,kind):
    # Only receive/beam/display controls: a review change must not carry transducer settings.
    patch = {section:copy.deepcopy(settings[section]) for section in ("beamformer","receive","display")}
    if kind=="detail":
        patch["beamformer"].update(cf=best["cf"],apod=best["apod"],accept_deg=best["accept"])
    (OUT/name).write_text(json.dumps(patch,indent=2)+"\n")
save_preset("balanced-reconstruction.json","balanced")
save_preset("wire-detail-reconstruction.json","detail")

def label(x):
    return f"{x[0]['lat_mm']:.2f} / {x[1]['lat_mm']:.2f} mm"
def font(px):
    return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf",px)
canvas = Image.new("RGB",(1140,374),"#151d25")
draw = ImageDraw.Draw(canvas)
titles = ["Original settings","Balanced","Wire detail"]
subs = ["Original RF | saved focus",
        "Corrected RF | 22 deg | coherence 0.15",
        f"Corrected RF | {best['accept']:g} deg | coherence {best['cf']:.2f}"]
for j,mag in enumerate((before,balanced,detail)):
    pixel = np.clip((db(mag/(46*4096)) +25+66)/66,0,1)
    u=2*pixel-1
    pix=np.uint8((.5+.5*np.sign(u)*abs(u)**.9)*255)
    frame=Image.fromarray(pix).resize((352,242),Image.Resampling.LANCZOS)
    left=j*380+16
    canvas.paste(frame,(left,70))
    draw.text((left,8),titles[j],font=font(21),fill="white")
    draw.text((left,43),subs[j],font=font(15),fill="#d5e4f3")
    for depth in (15,20,25,30):
        py=70+(depth-box[2])*11
        draw.line((left-4,py,left+2,py),fill="white")
    text = "Depth 10 to 32 mm" if j==0 else "Wire widths  "+label((baseline if j==1 else best)["wires"])
    draw.text((left,317),text,font=font(15),fill="#e5eaf1")
draw.text((16,350),"Same amplitude reference, +25 dB gain, 66 dB range and 0.90 curve throughout. Each panel spans 32 mm laterally.",font=font(14),fill="#bdcdda")
canvas.save(OUT/"comparison.png")
summary = {"sources":[str(raw),str(corrected)],"method":"Same full-scale reference and transfer for image panels. Compare linear envelopes in fixed per-wire ROIs. Wire-detail search requires <10 dB median loss in both gelatin patches, <2 dB peak loss on either wire, both flank p95 improved by >=2 dB, and <0.3 mm displacement from balanced. Rank by worst relative lateral width.",
           "balanced":baseline,"detail":best,"trials":candidates}
(OUT/"measurements.json").write_text(json.dumps(summary,indent=2))
print(json.dumps({k:summary[k] for k in ("balanced","detail")},indent=2))
