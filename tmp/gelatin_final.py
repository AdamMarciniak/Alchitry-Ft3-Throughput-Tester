from gelatin_analysis import *
from scipy.ndimage import gaussian_filter1d
s,cfg=load('flat-gain')
settings={'settings_schema':1,'note':'1 mm wire and two-layer psyllium gelatin, 2026-11-24. Validated on hardware RF; nominal speed 1531 m/s.'}
for key,fields in files.FIELDS.items():
    keys=list(fields)+files.BOOLS.get(key,[])
    settings[key]={k:cfg[key][k] for k in keys if k in cfg[key]}
settings['transmit'].update(trim_ns=cfg['transmit']['trim_ns'],single_elem=None,armed=False)
settings['beamformer'].update(apod=.2,cf=.28,accept_deg=25,dead=[25,46])
settings['receive'].update(avg_sweeps=8,matched_filter=True)
settings['display'].update(dyn_db=57,gain_db=40,curve=.85,auto_gain=False,debug_view=0,zoom=1.25,pan_cx=-.001,pan_cz=.029)
w.debug_apply(settings,replay=True)
h.recorded_tx_reference=s.tx_reference
files.atomic_json(root/'host/presets/gelatin-wire-19mm.json',settings)
r=s.rf[:]
side=(x[None,:]>-1)&(x[None,:]<7)&(z[:,None]>17)&(z[:,None]<21)
result={'validation':[]}
for start in [0,16,40]:
    m,im=render(r[start:start+8].mean(0))
    met=wire_metrics(m,box,search)
    info={k:met[k] for k in ['peak_position_mm','lateral_width_6db_mm','axial_width_6db_mm']}
    info.update(start_frame=start,peak_vs_same_depth_p95_db=float(20*np.log10(met['peak']/np.percentile(m[side],95))),central_gel_median_gray=float(np.median(array(im)[roi])))
    result['validation'].append(info)
annotated(im,out/'selected.png','Wire and gelatin   |   Final 8-sweep average')
# Direct ordinary-DAS split difference estimates only the time-varying floor.
h.state.update(cf=0,debug_view=1)
a=r[:8].mean(0);b=r[40:48].mean(0)
m1,_=render(a);m2,_=render(b);mean,_=render((a+b)/2);delta,_=render((a-b)/2)
result.update(central_23_36mm_split_repeatability=float(np.corrcoef(m1[roi],m2[roi])[0,1]),central_23_36mm_mean_over_halfdifference_db=float(20*np.log10(np.linalg.norm(mean[roi])/np.linalg.norm(delta[roi]))))
result['lateral_strip_profile_peaks_mm']=[]
for lo in [-8,-4,0,4]:
    prof=gaussian_filter1d(np.median(mean[:,(x>=lo)&(x<lo+4)],axis=1),3)
    gate=(z>=23)&(z<=29)
    result['lateral_strip_profile_peaks_mm'].append([lo,lo+4,round(float(z[gate][np.argmax(prof[gate])]),2)])
for name in ['baseline','near-gain','flat-gain']:
    sess,_=load(name);raw=sess.rf[:]
    valid=np.delete(raw,[25,46],axis=1)
    result[name]={'valid_frames':sum(q['valid'] for q in sess.quality),'clipped_samples':int(np.sum((valid<=-2048)|(valid>=2047)))}
    if name=='baseline':
        m0,im0=render(raw[40])
        result[name].update(central_gel_median_gray=float(np.median(array(im0)[roi])),wire_peak=wire_metrics(m0,box,search)['peak_position_mm'])
    sess.close()
files.atomic_json(out/'measurements.json',result)
print(json.dumps(result,indent=1))
h.stats['alive']=False;ren.close();w.close()
