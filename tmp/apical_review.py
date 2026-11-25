from gelatin_analysis import h, w, ren, files, root
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter
import numpy as np
import itertools
import copy
import json

src = root/'host/heart-apical-4chamber.rf.npz'
out = root/'bench_runs/apical-4ch-20261124'
out.mkdir(exist_ok=True)
s = files.load_session(src)
orig = s.metadata['review_settings']
w.debug_apply(orig,replay=True)
h.recorded_tx_reference = s.tx_reference
n = s.rf.shape[-1]
assert not h.HW and s.rf.shape==(208,48,9090)
alive = np.flatnonzero(h.alive_mask())
pair = alive.reshape(-1,2)
bits = np.random.default_rng(179).integers(0,2,len(pair))
halves = [pair[np.arange(len(pair)),a] for a in (bits,1-bits)]
mask = lambda a: h.set_dead(','.join(str(i) for i in range(48) if i not in a))
box = [-20,20,35,155]
dx,dz = .4,.2
nx,nz = round(40/dx),round(120/dz)
z = 35+(np.arange(nz)+.5)*dz
x = -20+(np.arange(nx)+.5)*dx
bands = [(45,70),(70,105),(105,135),(135,150)]
regions = [(z>=a)&(z<b) for a,b in bands]
train = [13,49,89,128,169,200]
hold = [3,33,72,109,150,185]
base=dict(lo=1,hi=7,apod=.63,cf=1.22,accept=26,c=1531,radius=71.6,pitch=.312,comp=False,mf=True)
moderate=dict(lo=1.5,hi=5,cf=.55)
options = {
    'recorded':{},
    'lighter coherence':dict(cf=.55),
    'broad moderate':moderate,
    'broad unweighted':dict(**{**moderate,'cf':0}),
    'stronger coherence':dict(**{**moderate,'cf':.85}),
    '2-4 MHz':dict(lo=2,hi=4,cf=.55),
    '2-5 MHz':dict(lo=2,hi=5,cf=.55),
    '3-6 MHz':dict(lo=3,hi=6,cf=.55),
    'wide angle':dict(**moderate,accept=33),
    'strong taper':dict(**moderate,apod=.85),
    'light taper':dict(**moderate,apod=.35),
    'measured geometry':dict(**moderate,radius=67.52,pitch=.3375),
    'speed 1490':dict(**moderate,c=1490),
    'speed 1560':dict(**moderate,c=1560),
    'three frequency bands':dict(**moderate,comp=True),
    'no pulse compression':dict(**moderate,mf=False)
}
caliper=dict(radius=61.1,pitch=.340)
for label,geometry in [('saved geometry',{}),('new calipers',caliper)]:
    for band,low,high in [('wide',1.5,5.0),('mid',1.8,4.8),('narrow',2,4)]:
        for weight in [0,.20]:
            options[f'{label} {band} CF{weight}']=dict(lo=low,hi=high,cf=weight,**geometry)
options['new calipers recorded filters']=caliper
options['new calipers mild taper']=dict(**caliper,lo=1.5,hi=5,cf=.20,apod=.40)
options['new calipers mild compound']=dict(**caliper,lo=1.5,hi=5,cf=.20,comp=True)

def setup(opt):
    p = dict(base,**opt)
    h.state.update(band_on=True,band_f0=(p['lo']+p['hi'])/2,band_bw=p['hi']-p['lo'],
                   cf=p['cf'],apod=p['apod'],c=p['c'],mf=p['mf'],freq_comp=p['comp'],
                   accept=p['accept'],auto=False,debug_view=0,curve=1,gain=37,dyn=95)
    h.geom.update(R_mm=p['radius'],pitch_mm=p['pitch'])
    h.rebuild_geometry()
    mask(alive)

def corr(a,b):
    a=a-a.mean(); b=b-b.mean()
    return float(np.sum(a*b)/max(np.sqrt(np.sum(a*a)*np.sum(b*b)),1e-16))

def metrics(an):
    fine,coarse=[],[]
    try:
        for half in halves:
            mask(half)
            m,_=ren.render(an,box,nx,nz)
            log=20*np.log10(np.maximum(m,1e-7))
            short=gaussian_filter(log,(.28/dz,.65/dx))
            med=gaussian_filter(log,(1.15/dz,1.9/dx))
            long=gaussian_filter(log,(3.5/dz,4.5/dx))
            fine.append(short-med)
            coarse.append(med-long)
    finally:
        mask(alive)
    area=abs(x)<12
    return [[corr(a[rows][:,area],b[rows][:,area]) for rows in regions] for a,b in (fine,coarse)]

def sweep():
    scores = {}
    for name,opt in options.items():
        setup(opt)
        row=[]
        for index in train+hold:
            frame=h.prepare_analytic(s.rf[index],n)
            row.append(metrics(frame))
        scores[name]=dict(parameters=dict(base,**opt),train=np.median(row[:len(train)],axis=0).round(4).tolist(),
                          holdout=np.median(row[len(train):],axis=0).round(4).tolist())
        print(name, np.round(np.mean(scores[name]['train'],axis=1),3),
              np.round(np.mean(scores[name]['holdout'],axis=1),3),flush=True)
    files.atomic_json(out/'comparison-metrics.json',dict(source=src.name,rf_sha256=s.metadata['rf_sha256'],
         train=train,holdout=hold,depth_bands_mm=bands,analysis_x_mm=[-12,12],active_halves=[v.tolist() for v in halves],
         metric='Median across frames of Pearson correlation between two disjoint aperture images. Rows: fine and coarse bandpass log-envelope textures. Columns: depth bands. Agreement can include coherent artifacts.',trials=scores))

def close():
    s.close(); h.stats['alive']=False;ren.close();w.close()

if __name__=='__main__':
    try: sweep()
    finally: close()
