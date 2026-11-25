from gelatin_analysis import h,files,ren,w,root,box,x,z,W,H,annotated,wire_metrics
import numpy as np
from scipy.ndimage import gaussian_filter
from PIL import Image,ImageDraw,ImageFont
import copy, json
out=root/'bench_runs/phantom-pulse-comparison'
names=['current','one-cycle','two-cycle','broad-chirp','golay','neighbor','current-repeat']
names += [p.name.split('.rf.npz')[0] for p in sorted(out.glob('hold-*.rf.npz'))]
def width(a):
    for lag in range(1,45):
        left=a[:,:-lag].ravel();right=a[:,lag:].ravel()
        corr=float(np.dot(left,right)/(np.linalg.norm(left)*np.linalg.norm(right)))
        if corr<.5:
            return 2*(lag-1+(prev-.5)/(prev-corr))/13
        prev=corr
def metrics(raw, cfg, dst, name, variant, anchor):
    h.state['debug_view']=1
    samps=cfg['acquisition']['win_words']*2
    def render(rf):
        return ren.render(h.prepare_analytic(rf,samps),box,W,H)
    mag,im=render(raw[:8].mean(0))
    later,_=render(raw[-8:].mean(0))
    diff,_=render((raw[:8].mean(0)-raw[-8:].mean(0))*.5)
    search=[-9,9,16.8,21.] if anchor is None else [anchor[0]-1.8,anchor[0]+1.8,anchor[1]-1.4,anchor[1]+1.4]
    met=wire_metrics(mag,box,search,anchor_mm=anchor)
    px,pz=met['peak_position_mm']
    roi=np.ix_((z>29)&(z<37),abs(x)<5.5)
    a=mag[roi].astype(float)
    grain=a/np.maximum(gaussian_filter(a,18),1e-8)-1
    side=(abs(x[None,:]-px)>2)&(abs(x[None,:]-px)<7)&(abs(z[:,None]-pz)<1.3)
    met.update(contrast_db=float(20*np.log10(met['peak']/np.percentile(mag[side],95))),
               grain_mm=[width(grain),width(grain.T)],background_rms_over_difference_db=float(20*np.log10(np.linalg.norm(mag[roi])/np.linalg.norm(diff[roi]))),
               background_repeat=float(np.corrcoef(a.ravel(),later[roi].ravel())[0,1]))
    mask=h.alive_mask()>0
    data=raw[:8,mask].reshape(8,-1, samps)
    region=slice(max(0,round((2*0.016/1531*1e6-h.state['dly_us'])*40)),round((2*0.04/1531*1e6-h.state['dly_us'])*40))
    met['clip_wire_gel_fraction']=float(np.mean((data[:,:,region]>=2047)|(data[:,:,region]<=-2048)))
    if dst:
        annotated(im,dst,f'{name}   |   8-sweep DAS   |   {variant}')
    return met
labels={'current':'Current chirp','one-cycle':'One cycle','two-cycle':'Two cycles','broad-chirp':'Broad chirp','golay':'Golay pair','neighbor':'Neighbor RX'}
results={}
anchor=None
if __name__=='__main__':
    try:
        for name in names:
            s=files.load_session(out/(name+'.rf.npz'))
            cfg=copy.deepcopy(s.metadata['acquired_settings'])
            w.debug_apply(cfg,replay=True)
            h.recorded_tx_reference=s.tx_reference
            raw=s.rf[:]
            row={}
            for variant,fc,bw,angle,taper in [('as-acquired',3.2,4.3,36,.81),('wide',4,6,30,.3),('fine',5,4,30,.3),('mid',4.5,5,30,.3)]:
                h.state.update(band_f0=fc,band_bw=bw,apod=taper,accept=angle,band_on=True,dyn=60,gain=28,curve=.85,auto=False)
                row[variant]=m=metrics(raw,cfg,out/f'{name}-{variant}.png',name,variant,anchor)
                if anchor is None: anchor=m['peak_position_mm']
                print(name,variant,'position',np.round(m['peak_position_mm'],2),'wire',round(m['lateral_width_6db_mm'] or 0,2),round(m['axial_width_6db_mm'] or 0,2),'contrast',round(m['contrast_db'],1),'grain',np.round(m['grain_mm'],2),'repeat',round(m['background_repeat'],3),'bg/diff',round(m['background_rms_over_difference_db'],1),flush=True)
            results[name]=row
            s.close()
        files.atomic_json(out/'measurements.json',results)
        sheet=Image.new('RGB',(3*(W+78),2*(H+80)),'#111820')
        for i,name in enumerate(names[:6]):
            sheet.paste(Image.open(out/f'{name}-wide.png'),((i%3)*(W+78),(i//3)*(H+80)))
        sheet.save(out/'six-methods.png')
    finally:
        h.stats['alive']=False
        ren.close();w.close()
