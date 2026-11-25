from gelatin_analysis import *
from scipy.ndimage import gaussian_filter1d
preset=json.loads((root/'host/presets/gelatin-wire-19mm.json').read_text())
results={}
renders=[]
for name,label in [('verified-live','Saved timing trims'),('final-live','Flat timing trims')]:
    s,cfg=load(name)
    for group in ['receive','beamformer','display']:
        cfg[group].update(preset[group])
    w.debug_apply(cfg,replay=True);h.recorded_tx_reference=s.tx_reference
    r=s.rf[:];result={}
    width=(x[None,:]>-8)&(x[None,:]<9)
    for mode in [0,1]:
        h.state.update(debug_view=mode)
        rows=[]
        for start in [0,16,40]:
            mag,im=render(r[start:start+8].mean(0))
            met=wire_metrics(mag,box,[-1,5,17,20.5])
            px,pz=met['peak_position_mm']
            side=(abs(x[None,:]-2)>2)&width&(abs(z[:,None]-18.5)<1.5)
            rows.append(dict(x_mm=px,z_mm=pz,lateral_mm=met['lateral_width_6db_mm'],axial_mm=met['axial_width_6db_mm'],peak_vs_background_p95_db=float(20*np.log10(met['peak']/np.percentile(mag[side],95))),gel_median_gray=float(np.median(array(im)[roi]))))
        result[['displayed','ordinary_DAS'][mode]]=rows
        if mode==0:
            path=out/(name+'-matched-display.png')
            annotated(im,path,label+'   |   Same reconstruction and display')
            renders.append(Image.open(path).copy())
            if name=='final-live':
                annotated(im,out/'final-wire-and-gel.png','Wire and surrounding gelatin   |   Final hardware capture')
        else:
            aa=r[:8].mean(0);bb=r[-8:].mean(0)
            u,_=render(aa);v,_=render(bb);d,_=render((aa-bb)/2)
            result.update(central_region_repeatability=float(np.corrcoef(u[roi],v[roi])[0,1]))
            if name=='final-live':
                result['local_peaks_within_23_to_29_mm']=[]
                for lo in [-8,-4,0,4]:
                    profile=gaussian_filter1d(np.median(mag[:,(x>=lo)&(x<lo+4)],axis=1),3)
                    mask=(z>=23)&(z<=29)
                    result['local_peaks_within_23_to_29_mm'].append(round(float(z[mask][profile[mask].argmax()]),2))
    valid=np.delete(r,[25,46],axis=1)
    result.update(valid_sweeps=sum(t['valid'] for t in s.quality),included_ADC_rail_samples=int(np.count_nonzero((valid<=-2048)|(valid>=2047))))
    results[name]=result
    s.close()
canvas=Image.new('RGB',(2*renders[0].width,renders[0].height));canvas.paste(renders[0],(0,0));canvas.paste(renders[1],(renders[0].width,0));canvas.save(out/'timing-comparison.png')
files.atomic_json(out/'final-measurements.json',results)
print(json.dumps(results,indent=1))
h.stats['alive']=False;ren.close();w.close()
