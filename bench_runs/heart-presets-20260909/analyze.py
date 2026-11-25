"""Compare the user's three stationary-intended heart clips; offline RF only."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'host'))
from rf_debug import load_session, atomic_json, validate_settings

SOURCES = {
    'baseline': ROOT / 'host/heart-baseline.rf.npz.rf.npz.rf.npz',
    'start': ROOT / 'host/heart-start.rf.npz.rf.npz.rf.npz',
    'tgc': ROOT / 'host/heart-tgc-latest.rf.npz.rf.npz.rf.npz',
}
GATES = [(13,20),(20,30),(30,40),(40,50),(50,60),(60,80),(80,100),(100,120),(120,140),(140,160)]
GOOD = [i for i in range(48) if i not in (25,46)]

def analyze(name, path):
    s = load_session(path)
    try:
        a = s.metadata['acquired_settings']
        fs = a['acquisition']['fs_hz']
        depth = (np.arange(s.rf.shape[2])/fs + a['acquisition']['dly_us']*1e-6)*a['beamformer']['c_m_s']/2*1000
        masks = [(depth>=lo)&(depth<hi) for lo,hi in GATES]
        valid = [i for i,q in enumerate(s.quality) if q['valid']]
        sampled = np.array(valid)[np.unique(np.linspace(0,len(valid)-1,min(64,len(valid))).astype(int))]
        clipping = np.zeros((len(GATES),48), np.int64)
        peaks = np.zeros(48)
        total_clipped = 0
        clipped_frames = []
        for i,frame in enumerate(s.rf):
            peaks = np.maximum(peaks,np.max(np.abs(frame.astype(np.int32)),axis=1))
            clip = (frame<=-2048)|(frame>=2047)
            count = int(clip.sum())
            if count:clipped_frames.append([i,count])
            total_clipped += count
            clipping += np.array([np.sum(clip[:,gate],axis=1) for gate in masks])
        bands = []
        for band in [(2,5),(2,4),(1,3),(3,5),(5,8)]:
            sos = butter(4,np.array(band)*1e6,btype='bandpass',fs=fs,output='sos')
            energies = []
            for i in sampled:
                filt = sosfiltfilt(sos,np.asarray(s.rf[i],float),axis=-1)
                energies.append([np.mean(filt[:,gate]**2,axis=1) for gate in masks])
            per_frame = np.sqrt(energies)
            rms = np.sqrt(np.mean(np.square(per_frame),axis=0))
            result = {'band_mhz':band,'rms_counts_by_depth_channel':rms.tolist(),
                      'included_channel_median_rms':np.median(rms[:,GOOD],axis=1).tolist(),
                      'quiet_pair_median_rms':np.median(rms[:,[25,46]],axis=1).tolist(),
                      'frame_median_rms_quantiles':np.quantile(np.median(per_frame[:,:,GOOD],axis=2),[.1,.5,.9],axis=0).tolist()}
            bands.append(result)
            print(name,band,'included',np.round(result['included_channel_median_rms'],3).tolist(),
                  'quiet',np.round(result['quiet_pair_median_rms'],3).tolist(),flush=True)
        sos = butter(4,[2e6,4e6],btype='bandpass',fs=fs,output='sos')
        corr = []
        previous = None
        previous_i = None
        for i in valid:
            filt = sosfiltfilt(sos,np.asarray(s.rf[i,GOOD],float),axis=-1)
            if previous is not None and i == previous_i+1:
                corr.append([float(np.sum(filt[:,gate]*previous[:,gate])/
                             max(np.sqrt(np.sum(filt[:,gate]**2)*np.sum(previous[:,gate]**2)),1e-20)) for gate in masks])
            previous,previous_i = filt,i
        result = {'name':name,'source':str(path),'created_utc':s.metadata['created_utc'],
                  'rf_sha256':s.metadata['rf_sha256'],'shape':list(s.rf.shape),
                  'valid_frames':len(valid),'duration_s':float(s.timestamps[-1]-s.timestamps[0]),
                  'settings':validate_settings(a),'review_settings':validate_settings(s.metadata['review_settings']),
                  'depth_gates_mm':GATES,'sampled_frames':sampled.tolist(),
                  'clipped_samples_total':total_clipped,'clipped_frames':clipped_frames,
                  'clipped_by_depth_channel':clipping.tolist(),'peaks_by_channel':peaks.tolist(),
                  'bands':bands,'adjacent_rf_correlation_2_4_mhz':np.quantile(corr,[.1,.5,.9],axis=0).tolist(),
                  'notes':['All samples checked for clipping. Depth/band power uses the stated subset.',
                           'Quiet channels are comparisons, not calibrated connected-channel noise measurements.',
                           'Between-clip amplitudes are confounded by acoustic window and physiological motion.',
                           'Correlation mixes noise, clutter and motion; it is not a cardiac velocity measurement.']}
        atomic_json(OUT / f'{name}-analysis.json',result)
        print(name,'frames',len(s.rf),'valid',len(valid),'seconds',round(result['duration_s'],3),'clipped',total_clipped,
              'correlation',np.round(result['adjacent_rf_correlation_2_4_mhz'][1],3).tolist(),flush=True)
        return result
    finally:s.close()

if __name__=='__main__':
    for name,path in SOURCES.items():analyze(name,path)
