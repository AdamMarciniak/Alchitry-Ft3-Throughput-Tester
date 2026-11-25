from gelatin_analysis import *
records=[]
for name in ['verified-live','flat-gain']:
    s,cfg=load(name); raw=s.rf[-8:].mean(0).astype('f4')
    h.state.update(cf=.28,apod=.2,accept=25,mf=True,dyn=61,gain=31,curve=.85,debug_view=0)
    ns=np.array(cfg['transmit']['trim_ns'])
    an=h.analytic(raw,raw.shape[1],ns/25)
    for angle in [17,20,25,30,35]:
        for apod in [.2,.45,.7]:
            h.state.update(accept=angle,apod=apod)
            m,im=ren.render(an,box,W,H)
            met=wire_metrics(m,box,search);px,pz=met['peak_position_mm']
            skip=(abs(x[None,:]-px)>2)&(abs(x[None,:])<9)&(abs(z[:,None]-pz)<1.5)
            arc=(abs(x[None,:]-px)>6)&(abs(z[:,None]-pz)<3)
            row={'source':name,'angle':angle,'apod':apod,'wx':met['lateral_width_6db_mm'],'wz':met['axial_width_6db_mm'],'contrast':float(20*np.log10(met['peak']/np.percentile(m[skip],95))),'outer_arc99_relative_db':float(20*np.log10(np.percentile(m[arc],99)/met['peak'])),'gel_median_gray':float(np.median(array(im)[roi]))}
            records.append(row)
    s.close()
files.atomic_json(out/'trim-aperture-replay.json',{'trials':records})
for row in records[:15]:print(row['angle'],row['apod'],*[round(row[k],2) for k in ['wx','contrast','outer_arc99_relative_db','gel_median_gray']])
h.stats['alive']=False;ren.close();w.close()
