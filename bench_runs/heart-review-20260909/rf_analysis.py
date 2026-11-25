from study import *
from scipy.signal import butter,sosfiltfilt
if __name__=='__main__':
    s=load_session(SOURCE)
    try:
        m=s.metadata;a=m['acquired_settings'];fs=a['acquisition']['fs_hz']
        depth=(np.arange(s.rf.shape[2])/fs+a['acquisition']['dly_us']*1e-6)*a['beamformer']['c_m_s']/2*1000
        bins=[(13,20),(20,30),(30,40),(40,50),(50,60),(60,80),(80,100),(100,120),(120,140),(140,160)]
        masks=[(depth>=lo)&(depth<hi) for lo,hi in bins]
        indices=np.unique(np.linspace(0,len(s.rf)-1,64).astype(int))
        bands=[(.5,1.5),(1,3),(1.5,3.5),(2,4),(2,5),(3,5),(5,8)]
        table=[]
        for lo,hi in bands:
            sos=butter(4,[lo*1e6,hi*1e6],btype='bandpass',fs=fs,output='sos')
            energy=np.zeros((len(bins),48));count=0
            for i in indices:
                rf=sosfiltfilt(sos,np.asarray(s.rf[i],float),axis=-1)
                energy+=np.array([np.mean(rf[:,gate]**2,axis=1) for gate in masks]);count+=1
            rms=np.sqrt(energy/count)
            table.append({'band_mhz':[lo,hi],'depth_bins_mm':bins,'rms_counts_by_depth_channel':rms.tolist()})
            good=[i for i in range(48) if i not in [25,46]]
            print('band',lo,hi,'healthy median by depth',np.round(np.median(rms[:,good],axis=1),3).tolist(),
                  'quiet median',np.round(np.median(rms[:,[25,46]],axis=1),3).tolist(),flush=True)
        maximum=np.zeros(48);clipped=np.zeros(48,dtype=np.int64)
        for frame in s.rf:
            maximum=np.maximum(maximum,np.max(np.abs(frame.astype(np.int32)),axis=1))
            clipped+=np.count_nonzero((frame<=-2048)|(frame>=2047),axis=1)
        result={'source':str(SOURCE),'rf_sha256':m['rf_sha256'],'frames':len(s.rf),'valid_frames':sum(q['valid'] for q in s.quality),
                'duration_s':float(s.timestamps[-1]-s.timestamps[0]),'max_adc_counts_by_channel':maximum.tolist(),
                'clipped_samples_by_channel':clipped.tolist(),'spectral_sample_frames':indices.tolist(),'band_depth_measurements':table,
                'settings':a,'note':'Quiet channels25/46 are comparison channels, not a calibrated independent measurement of every healthy channel noise floor.'}
        atomic_json(OUT/'rf-analysis.json',result)
        print('ALL FRAMES max',maximum.max(),'clipped',clipped.sum(),flush=True)
    finally:s.close()
