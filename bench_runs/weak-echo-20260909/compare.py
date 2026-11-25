from study import *

if __name__ == '__main__':
    for p in sorted(OUT.glob('*/weak-metrics.json')):
        m=json.loads(p.read_text())
        mag=np.load(p.parent/'magnitude.npy');xx,zz=axes(mag.shape)
        # Relative level is comparable across aperture taper, unlike raw sum.
        scale=38*4096*(1-.5*m['settings']['beamformer']['apod'])
        wx,wz=m['wire']['position_mm']; rr=np.hypot(xx-wx,zz-wz)
        distance=np.hypot(xx,zz)
        arc=(rr>4)&(abs(distance-np.hypot(wx,wz))<4)&(abs(xx)<27)
        arc &= np.hypot(xx-13.6,zz-53.3)>3
        patch=(abs(xx)<12)&(zz>23)&(zz<35)
        m['arc_p99']=float(np.percentile(mag[arc],99))
        m['background_rms']=float(np.sqrt(np.mean(mag[patch]**2)))
        m['normalized_peaks']={k:m[k]['peak']/scale for k in ['wire','weak1','weak2']}
        m['arc_to_wire_db']=float(20*np.log10(m['arc_p99']/m['wire']['peak']))
        atomic_json(p,m)
        if not p.parent.name.startswith('held'):
            print(p.parent.name, 'weak1 pos',m['weak1']['position_mm'],'weak2 pos',m['weak2']['position_mm'],
                  'norm weak1',round(m['normalized_peaks']['weak1'],7),
                  'arc dB',round(m['arc_to_wire_db'],1),'bg',round(m['background_rms']/scale,7))
