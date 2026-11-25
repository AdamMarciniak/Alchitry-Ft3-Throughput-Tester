"""Ask whether low zero-lag RF correlation improves with a bounded time shift.

This is a diagnostic of echo similarity, not a tissue-motion estimator or correction.
"""
import numpy as np
from scipy.signal import butter,sosfiltfilt
from scipy.fft import rfft,irfft,next_fast_len
from analyze import SOURCES,OUT,load_session,atomic_json

GATES=[(20,40),(40,60),(60,80),(80,120)]
GOOD=[i for i in range(48) if i not in (25,46)]
for name,path in SOURCES.items():
    s=load_session(path)
    try:
        a=s.metadata['acquired_settings'];fs=a['acquisition']['fs_hz']
        depth=(np.arange(s.rf.shape[2])/fs+a['acquisition']['dly_us']*1e-6)*a['beamformer']['c_m_s']/2*1000
        sos=butter(4,[2e6,4e6],btype='bandpass',fs=fs,output='sos')
        pairs=np.unique(np.linspace(0,len(s.rf)-2,32).astype(int))
        stats=[]
        for gate in GATES:
            mask=(depth>=gate[0])&(depth<gate[1]);n=int(mask.sum());nfft=next_fast_len(2*n-1)
            zero=[];best=[];quiet=[];lag=[]
            for i in pairs:
                if not s.quality[i]['valid'] or not s.quality[i+1]['valid']:continue
                f=sosfiltfilt(sos,np.asarray(s.rf[i:i+2],float),axis=-1)[:,:,mask]
                spec=rfft(f,n=nfft,axis=-1)
                corr=irfft(np.conj(spec[0])*spec[1],n=nfft,axis=-1)
                den=np.maximum(np.sqrt(np.sum(f[0]**2,axis=-1)*np.sum(f[1]**2,axis=-1)),1e-20)
                corr/=den[:,None]
                limited=np.concatenate([corr[:,-80:],corr[:,:81]],axis=-1)
                maximum=np.max(limited,axis=-1)
                zero.append(corr[GOOD,0]);best.append(maximum[GOOD]);quiet.append(maximum[[25,46]])
                lag.append((np.argmax(limited,axis=-1)-80)[GOOD])
            item={'range_mm':gate,'zero_lag_median':float(np.median(zero)),
                  'best_shift_correlation_median':float(np.median(best)),
                  'quiet_best_shift_correlation_median':float(np.median(quiet)),
                  'best_shift_samples_quantiles':np.quantile(lag,[.1,.5,.9]).tolist()}
            stats.append(item)
        atomic_json(OUT/f'{name}-motion-check.json',{'clip':name,'pair_indices':pairs.tolist(),'band_mhz':[2,4],
                    'max_lag_samples':80,'max_lag_us':2,'stats':stats,
                    'interpretation':'Maximum normalized RF correlation over +/-2us, with overlap attenuated by full-gate normalization. Lag search also increases random correlations; quiet controls are included. Does not identify which reflector moved, establish speed, or correct the sequential aperture.'})
        print(name,stats,flush=True)
    finally:s.close()
