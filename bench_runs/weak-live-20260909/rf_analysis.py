from study import *
from scipy.signal import butter,sosfiltfilt
if __name__=='__main__':
    summaries=[]
    sos=butter(4,[2e6,5e6],btype='bandpass',fs=40e6,output='sos')
    quiet=np.asarray(BASE['beamformer']['dead']);alive=np.array([i for i in range(48) if i not in quiet])
    for p in sorted(OUT.glob('*/capture.rf.npz')):
        s=load_session(p)
        try:
            rf=sosfiltfilt(sos,np.asarray(s.rf,dtype=float),axis=-1)
            acq=s.metadata['acquired_settings']['acquisition']
            depth=(np.arange(rf.shape[-1])/40e6+acq['dly_us']*1e-6)*1485/2*1000
            patch=rf[:,:,(depth>47)&(depth<60)]
            average=patch.mean(axis=0)
            residual=patch-average[None]
            per_channel=np.sqrt(np.mean(residual**2,axis=(0,2)))
            report=json.loads((p.parent/'capture.report.json').read_text())
            summary={'capture':p.parent.name,'frames':len(s.rf),
                     'tgc':acq['tgc_min'],'runtime_build_id':s.metadata['firmware_readback_before_arm']['runtime_build_id'],
                     'valid_frames':sum(q['valid'] for q in s.quality),
                     'max_adc_counts':max(e['peak_counts'] for e in report['elements']),
                     'clipped_channels':[e['element'] for e in report['elements'] if e['clipped_fraction']],
                     'healthy_median_temporal_residual_counts':float(np.median(per_channel[alive])),
                     'quiet_median_temporal_residual_counts':float(np.median(per_channel[quiet])),
                     'healthy_median_repeatable_rms_counts':float(np.median(np.sqrt(np.mean(average[alive]**2,axis=1)))),
                     'rf_sha256':s.metadata['rf_sha256'],
                     'note':'2–5 MHz filtered, 47–60 mm axial sample gate. Temporal residual includes motion and timing variation; not an isolated electronics-noise measurement.'}
            summaries.append(summary)
            print(json.dumps(summary),flush=True)
        finally:s.close()
    atomic_json(OUT/'rf-summary.json',summaries)
