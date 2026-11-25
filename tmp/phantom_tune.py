from gelatin_analysis import *
from scipy.ndimage import gaussian_filter
out=root/'bench_runs/phantom-pulse-comparison'
results=[]
s=files.load_session(out/'broad-chirp.rf.npz')
cfg=s.metadata['acquired_settings']
w.debug_apply(cfg,replay=True)
h.recorded_tx_reference=s.tx_reference
h.state.update(band_on=True,band_f0=4,band_bw=6,debug_view=1)
r=h.prepare_analytic(s.rf[:8].mean(0),h.cfg['samps'])
for radius,pitch in [(74.4,.335),(67.52,.3375),(71.6,.312)]:
    h.geom.update(R_mm=radius,pitch_mm=pitch);h.rebuild_geometry()
    for angle in [18,22,26,30,36]:
        for taper in [.3,.5,.7,.85]:
            h.state.update(apod=taper,accept=angle)
            m,im=ren.render(r,box,W,H)
            met=wire_metrics(m,box,[0,3.5,17,19.5])
            px,pz=met['peak_position_mm']
            side=(abs(x[None,:]-px)>2)&(abs(x[None,:]-px)<7)&(abs(z[:,None]-pz)<1.3)
            contrast=float(20*np.log10(met['peak']/np.percentile(m[side],95)))
            a=m[np.ix_((z>29)&(z<37),abs(x)<5.5)].astype(float)
            tex=a/np.maximum(gaussian_filter(a,18),1.e-9)-1
            ac=[np.corrcoef(tex[:,lag:].ravel(),tex[:,:-lag].ravel())[0,1] for lag in range(1,15)]
            g=2*np.interp(.5,[*reversed(ac),1],range(14,-1,-1))/13
            results.append([radius,pitch,angle,taper,round(met['lateral_width_6db_mm'],3),round(met['axial_width_6db_mm'],3),round(contrast,2),round(g,3),round(float(np.median(a)),1)])
files.atomic_json(out/'aperture-trials.json',dict(columns=['radius_mm','pitch_mm','angle_deg','taper','lateral_mm','axial_mm','contrast_db','lateral_grain_mm','gel_median_linear'],rows=results))
for q in sorted([q for q in results if q[6]>22 and q[4]<.8],key=lambda q:q[4]*q[5]*q[7])[:14]:print(q)
s.close();h.stats['alive']=False;ren.close();w.close()
