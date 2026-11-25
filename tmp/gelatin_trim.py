from gelatin_analysis import *
for name in ['verified-live','flat-gain']:
    s,cfg=load(name)
    h.state.update(cf=.28,apod=.2,accept=25,mf=True,dyn=57,gain=40,curve=.85,debug_view=0)
    raw=s.rf[-8:].mean(0).astype('f4')
    for pitch,rad in [(.312,71.6),(.3375,67.52)]:
        h.geom.update(R_mm=rad,pitch_mm=pitch);h.rebuild_geometry()
        for factor in [0,1,-1]:
            ns=factor*np.array(cfg['transmit']['trim_ns'])
            an=h.analytic(raw,raw.shape[1],ns/25)
            m,im=ren.render(an,box,W,H)
            met=wire_metrics(m,box,search)
            px,pz=met['peak_position_mm']
            side=(np.abs(x[None,:]-px)>2)&(abs(x[None,:])<9)&(abs(z[:,None]-pz)<1.5)
            contrast=20*np.log10(met['peak']/np.percentile(m[side],95))
            print(name,pitch,factor, 'peak',round(met['peak']),'p95 dB',round(float(contrast),1),'wx/z',round(met['lateral_width_6db_mm'],2),round(met['axial_width_6db_mm'],2),'x/z',round(px,2),round(pz,2),flush=True)
            if name=='verified-live' and pitch==.312:annotated(im,out/f'trim-review-{factor}.png',f'RF timing comparison   |   Trim multiplier {factor}')
h.stats['alive']=False;ren.close();w.close()
