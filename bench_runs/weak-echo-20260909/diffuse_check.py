"""Separate, deterministic SOFTWARE check. Never hardware or tissue validation.

2-D independent Gaussian point reflectors, linear single scattering, monostatic
round-trip delays, a Gaussian 3.5 MHz pulse, fractional sample interpolation.
No acoustic attenuation, elevation, aberration, real transducer response,
reverberation, nonlinear bubbles, or electronics are modelled.
"""
from study import *
from rf_debug import save_session, validate_settings
from scipy.signal import fftconvolve

if __name__ == '__main__':
    rng=np.random.default_rng(90521)
    settings=json.loads((ROOT/'host/presets/wire-21c-1mm-das.json').read_text())
    settings={k:v for k,v in settings.items() if k in ['acquisition','transmit','receive','beamformer','display','settings_schema']}
    settings.update(source='simulation',note=__doc__)
    settings['receive']['avg_sweeps']=1
    fs=40e6; c=1485.; delay=15e-6; samples=settings['acquisition']['win_words']*2
    count=120000
    sx=rng.uniform(-.035,.035,count); sz=rng.uniform(.015,.085,count)
    amp=rng.normal(0,1,count)
    # Left inclusion has half the scatterer amplitude; right is anechoic.
    hypo=np.hypot(sx+.010,sz-.058)<.006
    cyst=np.hypot(sx-.010,sz-.058)<.006
    amp[hypo]*=.5; amp[cyst]=0
    rad=.06752; pitch=.0003375
    angle=(np.arange(48)-23.5)*pitch/rad
    ex=rad*np.sin(angle); ez=rad*(np.cos(angle)-1)
    tt=np.arange(-40,41)/fs
    pulse=np.exp(-.5*(tt/.15e-6)**2)*np.cos(2*np.pi*3.5e6*tt)
    traces=[]
    for e in range(48):
        d=np.hypot(sx-ex[e],sz-ez[e]); t=(2*d/c-delay)*fs
        lo=np.floor(t).astype(int); frac=t-lo
        # Same monostatic geometry as the host; simple finite-element directivity.
        direction=np.arctan2(sx-ex[e],sz-ez[e])-angle[e]
        directivity=np.sinc(.00027*3.5e6/c*np.sin(direction))**2
        valid=(lo>=0)&(lo<samples-1)
        signal=np.bincount(lo[valid],weights=(amp*directivity*(1-frac))[valid],minlength=samples)
        signal+=np.bincount(lo[valid]+1,weights=(amp*directivity*frac)[valid],minlength=samples)
        traces.append(fftconvolve(signal,pulse,mode='same'))
    traces=np.asarray(traces)
    traces*=20/np.std(traces)
    traces[settings['beamformer']['dead']]=0
    frames=[np.rint(traces+rng.normal(0,.5,traces.shape)).astype(np.int16) for _ in range(4)]
    quality=[{'valid':True,'valid_elements':list(range(48)),'bad_elements':[],'missing_elements':[]} for _ in frames]
    path=OUT/'SIMULATION-diffuse.rf.npz'
    metadata={'acquired_settings':settings,'review_settings':settings,
              'simulation':{'seed':90521,'scatterers':count,'description':__doc__,
                            'hypoechoic_amplitude_ratio':.5,'cyst_amplitude_ratio':0,
                            'not_hardware_measurement':True}}
    save_session(path,frames,np.arange(4,dtype=float),metadata,quality,pulse)
    summary={}
    for cf in [0,.1,.2,.5,2]:
        name=f'SIMULATION-diffuse-cf{cf}'
        render(name,{'beamformer':{'cf':cf,'apod':.75}},frame=0,session=path)
        mag=np.load(OUT/name/'magnitude.npy');xx,zz=axes(mag.shape)
        rois={'background':(abs(xx)<20)&(zz>37)&(zz<45),
              'hypoechoic':np.hypot(xx+10,zz-58)<4,
              'cyst':np.hypot(xx-10,zz-58)<4}
        summary[str(cf)]={k:{'rms':float(np.sqrt(np.mean(mag[m]**2))),
                              'median':float(np.median(mag[m])),
                              'mean':float(np.mean(mag[m])),
                              'std':float(np.std(mag[m]))} for k,m in rois.items()}
    atomic_json(OUT/'SIMULATION-diffuse-summary.json',summary)
    print(json.dumps(summary),flush=True)
