from gelatin_analysis import *
s,cfg=load('flat-gain')
raw=s.rf[:8].mean(0)
side=(x[None,:]>-1)&(x[None,:]<7)&(z[:,None]>17)&(z[:,None]<21)
local=[-5.5,-3.5,17.3,20.4]
def met(m):
    d=wire_metrics(m,box,local)
    return dict(x=d['peak_position_mm'][0],z=d['peak_position_mm'][1],
        width=d['lateral_width_6db_mm'],axial=d['axial_width_6db_mm'],peak=d['peak'],
        contrast=float(20*np.log10(d['peak']/np.percentile(m[side],95))))
trials=[]
for f,bw in [(3.5,5),(3,3),(3,4),(3.5,3),(4,4),(2.5,2)]:
    for mf in [False,True]:
        for apod in [.2,.47,.75]:
            for ang in [25,35,50]:
                h.state.update(band_f0=f,band_bw=bw,mf=mf,apod=apod,accept=ang,cf=0,debug_view=1)
                m,_=render(raw)
                trials.append(dict(f=f,bw=bw,mf=mf,apod=apod,ang=ang,**met(m)))
for d in trials:
    d['score']=d['contrast']-12*np.log10(d['axial']*d['width'])
def show(t):print({k:round(float(v),3) for k,v in t.items()})
for t in sorted(trials,key=lambda t:-t['score'])[:8]:show(t)
with (out/'receive-trials.json').open('w') as fp:json.dump(trials,fp,indent=2)
h.stats['alive']=False;ren.close();w.close()
