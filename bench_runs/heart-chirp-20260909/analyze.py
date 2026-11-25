"""Reproducible, SIM-only review of the user's single long-chirp heart sweep."""
import copy
import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'host'))
from rf_debug import atomic_json, validate_settings
from test_rf_debug_ui import HostTests
from bench_render import Renderer

SOURCE = ROOT/'host/heart-chirp.rf.npz'
BOX = [-75,75,0,185]
W,H = 600,740  # isotropic 0.25 mm image pixels
GOOD = [i for i in range(48) if i not in (25,46)]
GATES = [(13,20),(20,40),(40,60),(60,80),(80,100),(100,120),(120,140),(140,160),(160,180)]
FONT = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 18)
SMALL = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 14)


def caption(im, title, subtitle, path):
    canvas=Image.new('RGB',(W+70,H+82),'#111820')
    d=ImageDraw.Draw(canvas)
    canvas.paste(im,(55,60))
    d.text((12,5),title,font=FONT,fill='white')
    d.text((12,32),subtitle,font=SMALL,fill='#b7c7d5')
    for z in range(0,181,20):
        y=60+z/185*H
        d.text((5,y-9),str(z),font=SMALL,fill='#b7c7d5')
        d.line((49,y,54,y),fill='#b7c7d5')
    d.text((5,H+61),'mm',font=SMALL,fill='#b7c7d5')
    d.text((205,H+61),'lateral -75 to +75 mm',font=SMALL,fill='#b7c7d5')
    canvas.save(path)


def run():
    HostTests.setUpClass()
    case=HostTests();case.setUp();h=case.h
    renderer=None
    try:
        assert not h.HW
        case.w.debug_open_rf(SOURCE,raise_errors=True)
        s=case.w.debug_session
        base=validate_settings(s.metadata['review_settings'])
        for section in ('acquisition','transmit'):
            base[section]=validate_settings(s.metadata['acquired_settings'])[section]
        rf=np.asarray(s.rf[0],np.float64)
        ref=np.array(s.tx_reference,copy=True)
        expected=h.pulser.tx_waveform(h.FS_HZ)
        checks={'source':str(SOURCE),'shape':list(s.rf.shape),'rf_sha256':s.metadata['rf_sha256'],
                'created_utc':s.metadata['created_utc'],'valid':s.quality[0]['valid'],
                'valid_elements':s.quality[0]['valid_elements'],
                'clipped_samples':int(((rf<=-2048)|(rf>=2047)).sum()),
                'adc_extrema':[int(rf.min()),int(rf.max())],
                'saved_reference_samples':len(ref),'reference_matches_current_command_generator':bool(np.array_equal(ref,expected)),
                'reference_energy':float(ref@ref),'settings':base}
        fs=h.FS_HZ;n=rf.shape[1]
        depth=(np.arange(n)/fs+base['acquisition']['dly_us']*1e-6)*1540/2*1000
        checks['depth_gates_mm']=GATES
        checks['bands']=[]
        profiles={}
        for band in [(1,2),(2,3),(3,4),(4,5),(5,6),(2,5)]:
            filt=sosfiltfilt(butter(4,np.array(band)*1e6,btype='bandpass',fs=fs,output='sos'),rf,axis=-1)
            rms=np.array([np.sqrt(np.mean(filt[:,(depth>=lo)&(depth<hi)]**2,axis=1)) for lo,hi in GATES])
            item={'mhz':band,'rms_counts_by_gate_channel':rms.tolist(),
                  'included_median':np.median(rms[:,GOOD],axis=1).tolist(),
                  'excluded_pair_median':np.median(rms[:,[25,46]],axis=1).tolist()}
            checks['bands'].append(item)
            print('RF band',band,'included',np.round(item['included_median'],3),
                  'excluded',np.round(item['excluded_pair_median'],3),flush=True)
        for lo,hi in [(20,40),(40,80),(80,120),(120,160)]:
            f,p=welch(rf[:,(depth>=lo)&(depth<hi)],fs=fs,nperseg=512,noverlap=256,axis=-1)
            profiles['frequency_mhz']=f/1e6
            profiles[f'psd-{lo}-{hi}mm-included']=np.median(p[GOOD],axis=0)
            profiles[f'psd-{lo}-{hi}mm-excluded']=np.median(p[[25,46]],axis=0)
        f=np.fft.rfftfreq(32768,1/fs)
        p=np.abs(np.fft.rfft(ref,n=32768))**2
        checks['command_reference_energy_fraction']={f'{lo}-{hi}MHz':float(p[(f>=lo*1e6)&(f<=hi*1e6)].sum()/p.sum()) for lo,hi in [(2,5),(2,6),(0,2),(5,20)]}
        profiles['reference_frequency_mhz']=f/1e6
        profiles['reference_power']=p
        profiles['rf_depth_mm']=depth
        profiles['reference']=ref
        renderer=Renderer(h)
        cases=[('saved','Saved: pulse compression ON',{}),
               ('off','Pulse compression OFF',{'receive':{'matched_filter':False}}),
               ('band-2-4','Compression ON, receive 2-4 MHz',{'receive':{'band_f0_mhz':3,'band_bw_mhz':2}}),
               ('band-1-5','Compression ON, receive 1-5 MHz',{'receive':{'band_f0_mhz':3,'band_bw_mhz':4}}),
               ('band-2-6','Compression ON, receive 2-6 MHz',{'receive':{'band_f0_mhz':4,'band_bw_mhz':4}}),
               ('apod-75','Compression ON, 75% apodization',{'beamformer':{'apod':.75}}),
               ('cf-015','Compression ON, coherence 0.15',{'beamformer':{'cf':.15}}),
               ('compound','Compression ON, frequency compound',{'receive':{'frequency_compounding':True}}),
               ('review','Replay option: 2-4 MHz, 75% apodization',
                {'receive':{'band_f0_mhz':3,'band_bw_mhz':2},'beamformer':{'apod':.75},
                 'display':{'dyn_db':85,'gain_db':27}}),
               ('inverse-010','Experimental: regularized inverse 0.10',{}),
               ('inverse-003','Experimental: regularized inverse 0.03',{}),
               ('hann','Experimental: Hann decode spectrum',{}),
               ('continuous-edge','Experimental: continuous-edge reference',{})]
        x=(np.arange(W)+.5)/W*150-75
        z=(np.arange(H)+.5)/H*185
        roi=(abs(x[None,:])<25)&(z[:,None]>=40)&(z[:,None]<140)
        checks['renders']=[]
        match_reference=None
        for name,title,patch in cases:
            settings=validate_settings(patch or base,copy.deepcopy(base))
            case.w.debug_apply(settings,replay=True)
            iq=h.prepare_analytic(case.w._review_rf(0),n,live=False)
            if name.startswith('inverse-') or name in ('hann','continuous-edge'):
                # These trials do not modify production code or the archived reference.
                nfft=h.next_fast_len(n+len(ref))
                freq=np.fft.fftfreq(nfft,1/fs)
                mask=h._hilb_mask(nfft,2e6,5e6)
                R=np.fft.fft(ref,nfft)
                if name.startswith('inverse-'):
                    strength=.10 if name.endswith('010') else .03
                    regularizer=strength*np.max(abs(R[(freq>=2e6)&(freq<=5e6)])**2)
                    decoder=np.conj(R)/(abs(R)**2+regularizer)
                elif name=='hann':
                    taper=np.where((freq>=2e6)&(freq<=5e6),.5-.5*np.cos(2*np.pi*(freq-2e6)/3e6),0)
                    decoder=np.conj(R)/float(ref@ref)*taper
                else:
                    # Exact continuous-time integrals of each 100 MHz-clock pulse.
                    # Unknown pulser/probe/AFE phase response is still uncalibrated.
                    R=np.zeros(nfft,complex);t=0.
                    for i,width in enumerate(h.pulser.chirp_table_now()):
                        duration=width/100e6
                        R+=(1 if i%2==0 else -1)*fs*duration*np.sinc(freq*duration)*np.exp(-2j*np.pi*freq*(t+duration/2))
                        t+=duration+h.pulser.t_dead_ns*1e-9
                    decoder=np.conj(R)/float(ref@ref)
                y=np.fft.ifft(np.fft.fft(rf,nfft,axis=1)*mask*decoder,axis=1)[:,:n]
                iq=np.stack([y.real,y.imag],axis=-1).astype(np.float32)
            mag,qim=renderer.render(iq,BOX,W,H)
            dest=OUT/name;dest.mkdir(exist_ok=True)
            qim.save(str(dest/'image.png'))
            np.save(dest/'magnitude.npy',mag)
            atomic_json(dest/'settings.json',settings)
            experimental=name.startswith('inverse-') or name in ('hann','continuous-edge')
            atomic_json(dest/'trial.json',{'name':name,'patch':patch,'source':str(SOURCE),
                'experimental_decoder':name if experimental else None,
                'reproduction':'Run analyze.py; settings.json alone does not implement the experimental decoder.' if experimental else 'Production host processing and beamformer.'})
            display=settings['display']
            caption(Image.open(dest/'image.png').convert('RGB'),title,
                    f"Display: {display['dyn_db']:g} dB range, {display['gain_db']:+g} dB gain",dest/'axes.png')
            scale=float(np.percentile(mag[roi],90))/h.full_scale(h.state['apod'])
            if match_reference is None:match_reference=scale
            adjustment=20*np.log10(match_reference/max(scale,1e-20))
            db=20*np.log10(mag/max(h.full_scale(h.state['apod']),1e-20)+1e-9)
            pixels=np.rint(np.clip((db+12+100+adjustment)/100,0,1)*255).astype(np.uint8)
            caption(Image.fromarray(pixels).convert('RGB'),title,f'Comparison only: brightness offset {adjustment:+.1f} dB',dest/'matched.png')
            checks['renders'].append({'name':name,'title':title,'patch':patch,'brightness_offset_db':float(adjustment)})
            if name in ('saved','off'):
                profiles[name+'-analytic-envelope']=np.hypot(iq[...,0],iq[...,1])
            print('render',name,'brightness offset',round(adjustment,2),flush=True)
        # Raw coherence map measures agreement, and is not a tissue validity score.
        settings=validate_settings({'display':{'debug_view':2}},copy.deepcopy(base))
        case.w.debug_apply(settings,replay=True)
        iq=h.prepare_analytic(case.w._review_rf(0),n,live=False)
        cf,_=renderer.render(iq,BOX,W,H)
        np.save(OUT/'coherence.npy',cf)
        checks['central_roi_coherence_quantiles']=np.quantile(cf[roi],[.1,.5,.9,.99]).tolist()
        checks['notes']=['One sweep cannot establish motion, repeatability, tissue resolution, or true tissue SNR.',
                         'Excluded channels 25 and 46 are imperfect noise comparators, not calibrated connected-channel noise.',
                         'Brightness-matched images use one scalar per image: 90th percentile in x +/-25 mm, z 40-140 mm. No local normalization.',
                         'Nine image variants use production processing; four explicitly labeled experiments replace only the decode filter offline. All use production beamforming. No source RF or geometry is changed.',
                         'The saved reference is a commanded electrical waveform, not a measured acoustic impulse response.',
                         'No hardware was opened, programmed or transmitted during this analysis.']
        np.savez_compressed(OUT/'profiles.npz',**profiles)
        atomic_json(OUT/'analysis.json',checks)
        print('CHECKS',json.dumps({k:v for k,v in checks.items() if k not in ('settings','bands','renders','notes')}),flush=True)
    finally:
        if renderer:renderer.close()
        case.tearDown()


if __name__=='__main__':run()
