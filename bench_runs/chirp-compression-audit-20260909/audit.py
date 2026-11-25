"""Audit production pulse compression using independent synthetic pulse echoes.

RF is synthesized from 100 MHz FPGA-table widths, filtered through an assumed
causal analog response, then resampled to 40 MSPS. No measured image is altered.
"""
import json
import sys
from pathlib import Path
import numpy as np
from scipy.signal import butter,sosfilt,resample_poly

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'host'))
from test_rf_debug_ui import HostTests
from rf_debug import atomic_json

def width6(envelope,fs):
    peak=int(np.argmax(envelope));threshold=envelope[peak]/2
    lo=hi=peak
    while lo>0 and envelope[lo-1]>=threshold:lo-=1
    while hi<len(envelope)-1 and envelope[hi+1]>=threshold:hi+=1
    def cross(a,b):
        return a+(threshold-envelope[a])/max(abs(envelope[b]-envelope[a]),1e-30)*np.sign(envelope[b]-envelope[a])
    if lo==0 or hi==len(envelope)-1:raise ValueError('Unbounded echo')
    samples=cross(hi,hi+1)-cross(lo-1,lo)
    return {'width_us':samples/fs*1e6,'width_mm_c1540':samples/fs*1540/2*1000,
            'peak_sample':peak,'peak':float(envelope[peak])}

HostTests.setUpClass()
case=HostTests();case.setUp();h=case.h
try:
    assert not h.HW
    h.state.update(band_on=True,band_f0=3.5,band_bw=3,freq_comp=False,debug_view=0)
    h.pulser.chirp_on=True;h.pulser.chirp_f0_mhz=5.2;h.pulser.chirp_f1_mhz=2.6;h.pulser.t_dead_ns=40
    n=8020;delay=2500;trials=[];arrays={}
    for analog_band in [(2,5),(2.8,3.6)]:
        for duration in [1,2,4,8,16]:
            h.pulser.chirp_us=duration;h.pulser.tx_gen+=1;h.recorded_tx_reference=None
            tab=h.pulser.chirp_table_now();dead=4
            drive=np.zeros(sum(w+dead for w in tab)+800,np.float64)
            pos=0
            for i,w in enumerate(tab):
                drive[pos:pos+w]=1 if i%2==0 else -1
                pos+=w+dead
            sos=butter(4,np.array(analog_band)*1e6,btype='bandpass',fs=100e6,output='sos')
            echo=resample_poly(sosfilt(sos,drive),2,5)
            rf=np.zeros((1,n),np.float32);rf[0,delay:delay+len(echo)]=echo
            cases=[]
            name=f'{analog_band[0]}-{analog_band[1]}MHz-{duration}us'
            for enabled in [False,True]:
                h.state['mf']=enabled
                iq=h.analytic(rf,n)[0];env=np.hypot(iq[:,0],iq[:,1])
                cases.append(width6(env,40e6))
                arrays[name+('-compressed' if enabled else '-raw')]=env
            trials.append({'chirp_us':duration,'assumed_analog_band_mhz':analog_band,
                           'compressed':cases[1],'uncompressed':cases[0],
                           'nominal_delay_samples':delay,'transmitted_table_halves':len(tab)})
            print(name,'raw/compressed mm',round(cases[0]['width_mm_c1540'],3),round(cases[1]['width_mm_c1540'],3),flush=True)
    # Wrong duration is a deliberately mismatched reference, not an observed bug.
    h.pulser.chirp_us=1;h.pulser.tx_gen+=1
    h.state['mf']=True
    iq=h.analytic(rf,n)[0];env=np.hypot(iq[:,0],iq[:,1])
    arrays['16us-narrow-echo-wrong-1us-reference']=env
    atomic_json(OUT/'results.json',{'source':'Synthetic audit only; not measured ultrasound',
        'signal_model':'100 MHz table-driven +/-1/0 waveform, assumed fourth-order causal analog Butterworth response, polyphase resampling to 40 MSPS. No noise, motion or nonlinearities.',
        'receive_band_mhz':[2,5],'width_definition':'Contiguous -6.02 dB amplitude width with linear crossing interpolation',
        'trials':trials,'wrong_reference_example':width6(env,40e6),
        'limits':['No new long-chirp RF was supplied.','These results validate algorithm behavior under the stated model, not the real probe response.',
                  'Compressed peak includes the assumed analog group delay; absolute depth needs its own calibration.']})
    np.savez(OUT/'profiles.npz',**arrays)
finally:case.tearDown()
