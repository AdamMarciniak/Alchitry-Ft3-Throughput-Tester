from study import *
from scipy.signal import butter,sosfiltfilt
if __name__=='__main__':
    s=load_session(SOURCE)
    try:
        n=s.rf.shape[-1];depth=(np.arange(n)/40e6+16e-6)*1540/2*1000
        gates=[(13,20),(20,30),(30,40),(40,60),(60,80),(80,120)]
        total=np.zeros((48,n));energy=np.zeros((48,n));cross=np.zeros((48,n));prev=None
        sos=butter(4,[2e6,4e6],btype='bandpass',fs=40e6,output='sos')
        frames=list(range(320,576))
        for i in frames:
            y=sosfiltfilt(sos,np.asarray(s.rf[i],float),axis=-1)
            total+=y;energy+=y*y
            if prev is not None:cross+=y*prev
            prev=y
        good=[i for i in range(48) if i not in [25,46]]
        results=[]
        for lo,hi in gates:
            gate=(depth>=lo)&(depth<hi)
            e=energy[good][:,gate].sum()/len(frames)
            mean_power=((total[good][:,gate]/len(frames))**2).sum()
            rho=(cross[good][:,gate].sum()/(len(frames)-1))/e
            results.append({'depth_mm':[lo,hi],'mean_waveform_power_fraction':float(mean_power/e),
                            'adjacent_sweep_zero_lag_correlation':float(rho)})
        clips=[]
        for i,f in enumerate(s.rf):
            for channel,sample in np.argwhere((f<=-2048)|(f>=2047)):
                clips.append({'frame':i,'channel':int(channel),'sample':int(sample),'depth_mm':float(depth[sample]),'adc':int(f[channel,sample])})
        atomic_json(OUT/'temporal-analysis.json',{'frames':frames,'nominal_aperture_ms':26.64,'gates':results,'clipped_samples':clips,
                     'note':'Temporal coherence is an RF statistic, not a direct measurement of cardiac motion. Low SNR and motion can both lower correlation; stable clutter can raise it.'})
        print(json.dumps(results,indent=2));print('clips',clips)
    finally:s.close()
