"""Check the original two-wire ADC data against held-out per-element delays."""
from pathlib import Path
import json
import sys
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import hilbert, butter, sosfiltfilt

here=Path(__file__).resolve().parent
root=here.parents[2]
sys.path.insert(0,str(root/'host'))
import rf_debug

s=rf_debug.load_session(root/'gelatin-2-wires.rf.npz')
try:
    a=s.metadata['acquired_settings']
    raw=s.rf[0].copy()
    valid=s.quality[0]['valid']
    sha=s.metadata['rf_sha256']
finally:
    s.close()
live=np.setdiff1d(np.arange(48),[25,46])
fs=a['acquisition']['fs_hz']/1e6
dly=a['acquisition']['dly_us']
time=dly+np.arange(raw.shape[1])/fs
filtered=sosfiltfilt(butter(4,[1.5,6.5],fs=fs,btype='bandpass',output='sos'),raw,axis=-1)
env=abs(hilbert(filtered,axis=1))
gate=(time>=23)&(time<=33)
idx=np.argmax(env[:,gate],axis=1)+np.flatnonzero(gate)[0]
# Quadratic interpolation near the peak of the RF envelope.
e=np.arange(48)
offset=.5*(env[e,idx-1]-env[e,idx+1])/(env[e,idx-1]+env[e,idx+1]-2*env[e,idx])
obs=dly+(idx+offset)/fs
trim=np.asarray(a['transmit']['trim_ns'])/1000
R,pitch,c=61.1,.3375,1528.
angle=(np.arange(48)-23.5)*pitch/R
ex=R*np.sin(angle)
ez=R*(np.cos(angle)-1.)
def predict(p,els,mode):
    wire=(els>25).astype(int)
    x=p[wire*2];z=p[wire*2+1]
    return 2000*np.hypot(x-ex[els],z-ez[els])/c+2.+mode*trim[els]

def fit(use,mode):
    return least_squares(lambda p:predict(p,use,mode)-obs[use],
                         [-7.3,19,8,20.5],loss='soft_l1',f_scale=.04).x

result=dict(source_adc_sha256=sha,valid_frame=bool(valid),shape=list(raw.shape),
            geometry=dict(c_m_s=c,pitch_mm=pitch,R_mm=R,t0_us=2),
            peak_fit_gate_us=[23,33],peak_fit_description="dominant echo per row, subsets IDs 0–24 and 26–47, excluding dead 25 and 46",
            active_wire_range_clip_count=int(((raw[live][:,gate]>=2047)|(raw[live][:,gate]<=-2048)).sum()),
            active_wire_range_sample_count=int(raw[live][:,gate].size),
            active_global_clip_count=int(((raw[live]>=2047)|(raw[live]<=-2048)).sum()),
            active_global_sample_count=int(raw[live].size))
for mode in [0,1]:
    errors=[]
    for parity in [0,1]:
        training=live[live%2==parity]
        test=live[live%2!=parity]
        p=fit(training,mode)
        errors.extend(1000*(predict(p,test,mode)-obs[test]))
    result[f"trim_scale_{mode}"]=dict(heldout_timing_rms_ns=float(np.sqrt(np.mean(np.square(errors)))),
        heldout_median_abs_ns=float(np.median(np.abs(errors))),
        fitted_wire_positions_mm=fit(live,mode).tolist())

est=fit(live,1)
for w in [0,1]:
    x,z=est[2*w:2*w+2]
    norm=np.hypot(x-ex,z-ez)
    cos=((x-ex)*np.sin(angle)+(z-ez)*np.cos(angle))/norm
    ids=live[cos[live]>=np.cos(np.radians(22))]
    obs_row=live[live<25] if w==0 else live[live>25]
    pulse=raw[obs_row[:,None],idx[obs_row,None]+np.arange(-32,33)]*np.hanning(65)
    spec=abs(np.fft.rfft(pulse-pulse.mean(axis=1,keepdims=True),n=512,axis=1))**2
    freq=np.fft.rfftfreq(512,1/fs)
    good=(freq>=1)&(freq<=8)
    p=np.sum(spec,axis=0)
    peaks=freq[good][np.argmax(p[good])]
    peak=env[obs_row,idx[obs_row]]
    result[f"wire_{w+1}"]=dict(angle_eligible_channels=len(ids),
                angle_eligible_aperture_span_mm=float(np.ptp(ex[ids])),
                dominant_echo_channels=len(obs_row),
                strongest_half_amplitude_channels=int(sum(peak>=peak.max()*.5)),
                observed_wire_spectrum_peak_mhz=float(peaks),
                observed_wire_spectrum_power_centroid_1to8mhz=float(np.dot(freq[good],p[good])/p[good].sum()))
with (here/'raw_check.json').open('w') as f:
    json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
