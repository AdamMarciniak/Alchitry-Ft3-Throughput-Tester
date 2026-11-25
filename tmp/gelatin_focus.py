from gelatin_analysis import *
s,cfg=load('flat-gain')
raw=s.rf[:8].mean(0)
def assess():
    m,_=render(raw)
    met=wire_metrics(m,box,[-5.5,-3.5,17.3,20.4])
    peak=met['peak']
    xs,zs=met['peak_position_mm']
    # Same-depth central background, away from the wire and beam edges.
    side=(x[None,:]>-1)&(x[None,:]<7)&(z[:,None]>17)&(z[:,None]<21)
    return {'width':met['lateral_width_6db_mm'],'axial':met['axial_width_6db_mm'],'peak':peak,
       'x':xs,'z':zs,'contrast':float(20*np.log10(peak/np.percentile(m[side],95)))}
h.state.update(cf=0,debug_view=1)
trials=[]
for pitch,radius in [(0.312,71.6),(.3375,67.52)]:
    h.geom.update(R_mm=radius,pitch_mm=pitch);h.rebuild_geometry()
    for speed in [1490,1510,1531,1550,1570]:
        for delay in [20,480,960,1440]:
            h.state.update(c=speed,t0_ns=delay)
            m=assess()
            trials.append(dict(pitch=pitch,R=radius,c=speed,t0_ns=delay,**m))
def show(items):
    for t in items: print({k:round(float(v),3) for k,v in t.items()})
show(sorted(trials,key=lambda t:-t['contrast'])[:6])
print('baseline');show([t for t in trials if t['c']==1531 and t['t0_ns']==20])
with (out/'focus-trials.json').open('w') as fp:json.dump(trials,fp,indent=2)
h.stats['alive']=False;ren.close();w.close()
