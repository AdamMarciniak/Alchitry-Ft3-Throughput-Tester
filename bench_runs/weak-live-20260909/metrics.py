from study import *
ROIS={'wire':(-3.2,40.4,1.7,1.2),'faint_right':(18,37.7,1.8,1.2),'faint_left':(-20.6,36.2,1.8,1.2)}

def measure(name):
    path=OUT/name
    t=json.loads((path/'trial.json').read_text())
    mag=np.load(path/'magnitude.npy');xx,zz=axes(mag.shape,t['box_mm'])
    apod=t['settings_patch']['beamformer']['apod']
    scale=38*4096*(1-.5*apod)
    m={'trial':name,'source':t['session'],'frame':t['frame'],'aperture_scale':scale}
    for k,(x,z,wx,wz) in ROIS.items():
        gate=(abs(xx-x)<wx)&(abs(zz-z)<wz)
        ij=np.unravel_index(np.argmax(np.where(gate,mag,-1)),mag.shape)
        px,pz=float(xx[ij]),float(zz[ij]);rr=np.hypot(xx-px,zz-pz)
        bg=(rr>2)&(rr<4.5)
        peak=float(mag[ij]);rms=float(np.sqrt(np.mean(mag[bg]**2)))
        m[k]={'peak':peak,'normalized_peak':peak/scale,'position_mm':[px,pz],
              'local_rms':rms,'local_db':float(20*np.log10(max(peak,1e-10)/max(rms,1e-10)))}
    quiet=(abs(xx)<12)&(zz>47)&(zz<60)
    radius=np.hypot(xx,zz)
    arc=(abs(radius-40.5)<3)&(abs(xx)<28)
    for x,z,_,_ in ROIS.values():arc &= np.hypot(xx-x,zz-z)>3
    m['quiet_rms']=float(np.sqrt(np.mean(mag[quiet]**2)))
    m['arc_p99_relative_db']=float(20*np.log10(np.percentile(mag[arc],99)/max(m['wire']['peak'],1e-10)))
    atomic_json(path/'weak-metrics.json',m)
    print(name,json.dumps({k:{'peak':round(v['peak'],2),'local_db':round(v['local_db'],2),'xy':v['position_mm']} for k,v in m.items() if k in ROIS}),flush=True)
    return m

if __name__=='__main__':
    for p in sorted(OUT.glob('*/trial.json')):
        if 'cfmap' not in p.parent.name:measure(p.parent.name)
