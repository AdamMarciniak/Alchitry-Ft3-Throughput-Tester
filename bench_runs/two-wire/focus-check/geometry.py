"""Replay-only focus sensitivity given the same timing-corrected RF."""
from pathlib import Path
import os
import sys
import json
import numpy as np

out=Path(__file__).resolve().parent
root=out.parents[2]
sys.path.insert(0,str(root/'host'))
sys.argv=['tfm_gl_host.py','sim']
os.environ['QT_QPA_PLATFORM']='offscreen'
import tfm_gl_host as h
import rf_debug
from bench_render import Renderer, _width

box=[-12,12,15,27]
W,H=768,384
x=box[0]+(np.arange(W)+.5)/32
z=box[2]+(np.arange(H)+.5)/32
app=h.QApplication(sys.argv)
window=h.Main()
renderer=Renderer(h)
session=rf_debug.load_session(out.parent/'gelatin-2-wires-trim-comp.rf.npz')
try:
    cfg=json.loads((root/'host/presets/gelatin-two-wire-best.json').read_text())
    window.debug_apply(cfg,replay=True)
    h.recorded_tx_reference=session.tx_reference
    h.state.update(debug_view=1)
    rf=h.prepare_analytic(session.rf[0],h.cfg['samps'])
    def evaluate(radius,pitch,speed,zero):
        h.geom.update(R_mm=radius,pitch_mm=pitch)
        h.rebuild_geometry()
        h.state.update(c=speed,t0_ns=zero)
        mag,_=renderer.render(rf,box,W,H)
        wires=[]
        for x0,z0 in [(-7.2,18.7),(7.7,20.2)]:
            gate=(abs(z[:,None]-z0)<1.8)&(abs(x[None,:]-x0)<1.5)
            iz,ix=np.unravel_index(np.argmax(np.where(gate,mag,-1)),mag.shape)
            dx,dz=abs(x[None,:]-x[ix]),abs(z[:,None]-z[iz])
            side=(dx>1.3)&(dx<4.3)&(dz<.7)
            wires.append(dict(x=float(x[ix]),z=float(z[iz]),lat=_width(mag[iz],x,ix),
                axial=_width(mag[:,ix],z,iz),peak=float(mag[iz,ix]),
                near_p95_db=float(20*np.log10(np.percentile(mag[side],95)/mag[iz,ix]))))
        return dict(R_mm=radius,pitch_mm=pitch,c=speed,t0_ns=zero,wires=wires)

    nominal=evaluate(67.02,.3325,1490,1900)
    results=[]
    for R,p in [(61.1,.34),(61.1,.3375),(67.52,.3375),(67.02,.3325)]:
        for c in [1480,1490,1500,1510,1520,1530,1540]:
            for t in [1700,1900,2000,2100,2300,2500]:
                results.append(evaluate(R,p,c,t))
    def eligible(a):
        return all(q['near_p95_db']<=r['near_p95_db']+1 and q['peak']>.94*r['peak']
                   and q['axial']<=1.06*r['axial'] for q,r in zip(a['wires'],nominal['wires']))
    def worst_width_ratio(a):
        return max(v['lat']/u['lat'] for v,u in zip(a['wires'], nominal['wires']))
    feasible=[r for r in results if eligible(r)]
    best=min(feasible,key=worst_width_ratio)
    measured=min((r for r in feasible if r['R_mm']==61.1),key=worst_width_ratio)
    report=dict(pixel_mm=1/32,selection="minimize worse of the two lateral width ratios, each wire near P95 < baseline+1 dB, each axial width within +6%, each peak >=94% of baseline",
        reference=nominal,best=best,best_R61_1=measured,results=results)
    rf_debug.atomic_json(out/'geometry.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
finally:
    session.close()
    h.stats['alive']=False
    renderer.close()
    window.close()
