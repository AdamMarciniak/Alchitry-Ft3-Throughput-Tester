from gelatin_analysis import *
from scipy.ndimage import gaussian_filter
s,cfg=load('final-live')
preset=json.loads((root/'host/presets/gelatin-wire-19mm.json').read_text())
raw=s.rf[:]
source=raw[:8].mean(0)
def widths(m):
    sizes=[]
    for za,zb in [(21,29),(30,38)]:
        a=m[np.ix_((z>=za)&(z<zb),abs(x)<5.5)].astype(float)
        a=a/np.maximum(gaussian_filter(a,24),1e-8)-1
        wh=[]
        for vec in [a,a.T]:
            corr=[1.]
            for lag in range(1,35):
                lo=vec[:,:-lag].ravel();hi=vec[:,lag:].ravel()
                corr.append(np.dot(lo,hi)/(np.linalg.norm(lo)*np.linalg.norm(hi)))
                if corr[-1] <= .5:break
            wh.append(2*(lag-1+(corr[-2]-.5)/(corr[-2]-corr[-1]))/13)
        sizes.append(wh)
    return np.array(sizes)
def setup(angle,taper,mf,freq,bw):
    h.state.update(accept=angle,apod=taper,mf=mf,band_f0=freq,band_bw=bw)
def get(raw,mode):
    h.state['debug_view']=mode
    mag,im=render(raw)
    met=wire_metrics(mag,box,[-1,5,17,20.5]);side=(abs(x[None,:]-2)>2)&(x[None,:]>-8)&(x[None,:]<9)&(abs(z[:,None]-18.5)<1.5)
    return dict(grain=widths(mag).tolist(),wire=[met['lateral_width_6db_mm'],met['axial_width_6db_mm']],contrast=float(20*np.log10(met['peak']/np.percentile(mag[side],95))),gray=float(np.median(array(im)[roi]))),im
if __name__=='__main__':
    trials=[]
    for angle,taper in [(20,.45),(25,.3),(30,.3),(35,.2),(30,.45)]:
        for mf in [True,False]:
            for freq,bw in [(3.5,5),(4,6),(4.5,5),(5,5),(5,4),(5.5,4)]:
                par=(angle,taper,mf,freq,bw);setup(*par);result,im=get(source,1)
                trials.append(dict(p=par,**result))
    files.atomic_json(out/'speckle-replay-trials.json',{'trials':trials})
    base=trials[0]; print('BASE',base)
    for row in sorted([r for r in trials if r['contrast']>=base['contrast']-3 and r['gray']>=base['gray']-24],key=lambda r:np.prod(np.mean(r['grain'],axis=0)))[:7]:print(row)
    h.stats['alive']=False;ren.close();w.close()
