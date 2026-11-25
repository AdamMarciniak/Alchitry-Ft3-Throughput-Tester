"""Recorded commands and analysis for this physical 21 C / 1 mm wire session."""
import copy
import json
from pathlib import Path
import sys
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'host'))
from bench_client import request
from rf_debug import load_session, atomic_json

OUT=Path(__file__).resolve().parent
CONTROL=ROOT/'bench_runs/control'
NOTE='Owner-confirmed fixed bath: approximately 21 C, 1 mm wire near 5 cm, container bottom near 10 cm, possible bubbles. Existing +/-40 V. Water model c=1485 m/s.'
BOX=[-50,50,0,120]
SEARCH=[-12,8,43,59]
ANCHOR=[-3.4,51.3]

def capture(name, patch, frames=24):
    configured=request(CONTROL, {'op':'configure','settings':patch})
    atomic_json(OUT/(name+'-requested-settings.json'),configured)
    result=request(CONTROL, {'op':'capture','frames':frames,'timeout_s':25,
                    'output':str(OUT/name),'note':NOTE+' Condition: '+name},timeout=40)
    print('CAPTURE',name,json.dumps(result),flush=True)
    return result

def render(name, session, patch=None, frame=0, anchor=ANCHOR, box=BOX):
    result=request(CONTROL, {'op':'render','session':str(OUT/session/'capture.rf.npz'),
                    'frame':frame,'settings':patch or {'display':{'debug_view':1,'gain_db':35,'dyn_db':80}},
                    'box_mm':box,'search_mm':SEARCH,'anchor_mm':anchor,
                    'output':str(OUT/name)},timeout=60)
    m=result['metrics']
    mag=np.load(OUT/name/'magnitude.npy')
    height,width=mag.shape
    x=box[0]+(np.arange(width)+.5)*(box[1]-box[0])/width
    z=box[2]+(np.arange(height)+.5)*(box[3]-box[2])/height
    xx,zz=np.meshgrid(x,z)
    ax,az=(-4.59,51.1)
    radius=67.52
    arc=(np.abs(np.hypot(xx,zz+radius)-np.hypot(ax,az+radius))<4)&(np.abs(xx-ax)>5)
    signal=(np.abs(xx-ax)<3)&(np.abs(zz-az)<2)
    values=mag[arc]
    m['wide_arc_p99_db']=float(20*np.log10(max(np.percentile(values,99),1e-12)/m['peak']))
    m['wide_arc_max_db']=float(20*np.log10(max(values.max(),1e-12)/m['peak']))
    m['wide_arc_energy_ratio']=float(np.sum(values**2)/max(np.sum(mag[signal]**2),1e-12))
    atomic_json(OUT/name/'metrics.json',m)
    atomic_json(OUT/name/'trial.json',dict(result,patch=patch))
    print('RENDER',name,json.dumps({k:m[k] for k in ['peak_position_mm','lateral_width_6db_mm','axial_width_6db_mm','clutter_p95_relative_db','clutter_to_target_energy','normalized_peak']}),flush=True)
    return result

def search():
    session='flat-trim-tgc2200'
    quiet=[2,3,6,7,18,19,22,23,25,46]
    common={'receive':{'avg_sweeps':1,'frequency_compounding':False,'matched_filter':False},
            'beamformer':{'dead':quiet,'cf':0,'t0_ns':0,'c_m_s':1485},
            'display':{'debug_view':1,'gain_db':40,'dyn_db':60,'curve':1,'auto_gain':False}}
    trials=[]
    for centre,bw in [(2,1),(2,2),(2.5,1),(2.5,2),(3,2),(3.5,3),(4,5)]:
        for apod in [0,.5,1]:
            patch=copy.deepcopy(common)
            patch['receive'].update(bandpass_on=True,band_f0_mhz=centre,band_bw_mhz=bw)
            patch['beamformer']['apod']=apod
            name=f'search-f{centre}-bw{bw}-a{apod}'
            item=render(name,session,patch,frame=8)
            item['patch']=patch
            trials.append(item)
    atomic_json(OUT/'wide-search.json',trials)
    for item in sorted(trials,key=lambda t:t['metrics']['wide_arc_p99_db'])[:10]:
        print('WIDE ARC',Path(item['output']).name,json.dumps({k:item['metrics'][k] for k in ['wide_arc_p99_db','wide_arc_max_db','normalized_peak','lateral_width_6db_mm']}),flush=True)

def rf_summary(session):
    s=load_session(OUT/session/'capture.rf.npz')
    try:
        a=s.rf.astype(np.float32)
        settings=s.metadata['acquired_settings']
        c=settings['beamformer']['c_m_s']
        d=(np.arange(a.shape[-1])/40e6+settings['acquisition']['dly_us']*1e-6)*c*500
        rows=[]
        for e in range(48):
            traces=np.stack([a[i,e] for i,q in enumerate(s.quality) if e in q['valid_elements']])
            row={'element':e,'clipped_fraction':float(np.mean(np.abs(traces)>=2047))}
            for name,lo,hi in [('wire',43,59),('quiet',60,70),('bottom',80,110)]:
                gated=traces[:,(d>=lo)&(d<=hi)]
                row[name+'_rms']=float(np.sqrt(np.mean(gated**2)))
                row[name+'_peak']=float(np.max(np.abs(gated)))
            rows.append(row)
        result={'session':session,'valid_frames':sum(q['valid'] for q in s.quality),'elements':rows}
        atomic_json(OUT/session/'gated-rf.json',result)
        print('RF',session,'valid',result['valid_frames'],'clipmax',max(r['clipped_fraction'] for r in rows),
              'wireRMS',np.round([r['wire_rms'] for r in rows],1).tolist(),flush=True)
        return result
    finally:
        s.close()

if __name__=='__main__':
    if sys.argv[1]=='gain':
        rf_summary('gap300')
        render('gap300-image','gap300')
        for gain in (1800,2200,2600):
            name='flat-tgc-'+str(gain)
            capture(name,{'acquisition':{'tgc_min':gain,'tgc_max':gain,'damp_gap_us':300}})
            rf_summary(name)
            render(name+'-image',name)
    elif sys.argv[1]=='search':
        search()
