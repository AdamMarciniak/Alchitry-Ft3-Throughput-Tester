from phantom_compare import h, files, ren, w, root, box, x, z, W, H, annotated, wire_metrics
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
out=root/'bench_runs/three-position-rx'
rows={}
anchor=None
def db(ratio): return float(20*np.log10(max(ratio,1e-12)))
for name in ['broad','broad-matched','three-rx','broad-matched-repeat','three-rx-repeat','final-live']:
    path=out/(name+'.rf.npz')
    if not path.exists(): continue
    s=files.load_session(path)
    cfg=s.metadata['acquired_settings']
    w.debug_apply(cfg,replay=True)
    h.recorded_tx_reference=s.tx_reference
    h.state['debug_view']=1
    n=h.cfg['samps']
    masks=h.multi_rx_weights().ravel()>0 if h.pulser.shot_method==3 else h.alive_mask()>0
    results=[]
    for i in [0,16,32]:
        raw=s.rf[i:i+8].mean(0)
        an=h.prepare_analytic(raw,n)
        mag,im=ren.render(an,box,W,H)
        search=[-8,8,17,20.5] if anchor is None else [anchor[0]-1.2,anchor[0]+1.2,anchor[1]-.7,anchor[1]+.7]
        wire=wire_metrics(mag,box,search)
        if anchor is None: anchor=wire['peak_position_mm']
        dx=np.abs(x[None,:]-anchor[0]);dz=np.abs(z[:,None]-anchor[1])
        side=(dx>2)&(dx<7)&(dz<1.3)
        far=(dx>=7)&(dx<=15)&(dz<1.5)
        gel=np.ix_((z>29)&(z<37),np.abs(x)<5.5)
        ref,_=ren.render(h.prepare_analytic(s.rf[i+8:i+16].mean(0),n),box,W,H)
        delta,_=ren.render(h.prepare_analytic((s.rf[i+8:i+16].mean(0)-raw)*.5,n),box,W,H)
        results.append(dict(xz_mm=wire['peak_position_mm'],lat_mm=wire['lateral_width_6db_mm'],ax_mm=wire['axial_width_6db_mm'],
                            near_contrast=db(wire['peak']/np.percentile(mag[side],95)),far_contrast=db(wire['peak']/np.percentile(mag[far],95)),
                            gel_repeat=float(np.corrcoef(mag[gel].ravel(),ref[gel].ravel())[0,1]),
                            gel_over_diff_db=db(np.linalg.norm(mag[gel])/np.linalg.norm(delta[gel]))))
        if i==0:
            h.state['debug_view']=0
            displayed,image=ren.render(h.prepare_analytic(raw,n),box,W,H)
            annotated(image,out/(name+'.png'),('Three receive positions' if h.pulser.shot_method==3 else 'Single receive position')+f"  |  {h.state['dly_us']:.0f} µs gate")
            h.state['debug_view']=1
    rows[name]=dict(windows=results,rate=47/float(s.timestamps[-1]-s.timestamps[0]),valid=sum(q['valid'] for q in s.quality),
                    contributing_paths=int(masks.sum()),build=s.metadata['firmware_readback_before_arm']['runtime_build_id'])
    print(name,'rate',round(rows[name]['rate'],1),'paths',int(masks.sum()),{k:np.round(v,3) for k,v in results[-1].items()})
    s.close()
files.atomic_json(out/'wire-comparison.json',dict(records=rows,anchor=anchor,side_roi='2-7 mm lateral, ±1.3 mm axial from baseline wire',far_roi='7-15 mm lateral, ±1.5 mm axial from baseline wire',gel_roi='x ±5.5 mm, z 29-37 mm'))
names=['broad-matched','three-rx']
imgs=[Image.open(out/(n+'.png')).convert('RGB') for n in names]
page=Image.new('RGB',(2*imgs[0].width,imgs[0].height),'#111820')
for i,im in enumerate(imgs):page.paste(im,(im.width*i,0))
page.save(out/'comparison.png')
h.stats['alive']=False;ren.close();w.close()
