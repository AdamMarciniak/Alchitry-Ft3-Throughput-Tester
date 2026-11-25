"""Replay actual recorded RF in the SIM-only bench host; no acquisition."""
import copy
import json
import numpy as np
from analyze import ROOT, OUT, SOURCES
from bench_client import request
from rf_debug import atomic_json

CONTROL = ROOT / 'bench_runs/heart-presets-offline'
BOX = [-65,65,0,165]
COMMON = {'receive':{'bandpass_on':True,'band_f0_mhz':3.5,'band_bw_mhz':3,
                     'avg_sweeps':1,'matched_filter':False,'frequency_compounding':False,
                     'bg_subtract':False,'dejitter_on':False},
          'beamformer':{'cf':0,'apod':.75,'dead':[25,46]},
          'display':{'dyn_db':95,'gain_db':15,'curve':1,'auto_gain':False,'debug_view':0}}

def render(name, frame, label='common', patch=None):
    out = OUT / f'{name}-{label}-f{frame}'
    if out.exists():return
    supplied = COMMON if patch is None else patch
    request(CONTROL,{'op':'render','session':str(SOURCES[name]),'frame':int(frame),'settings':supplied,
                    'box_mm':BOX,'search_mm':[-25,25,35,140],'output':str(out)},timeout=60)
    atomic_json(out/'trial.json',{'clip':name,'frame':int(frame),'source':str(SOURCES[name]),'patch':supplied,'label':label})
    print(out.name,flush=True)

if __name__=='__main__':
    for name in SOURCES:
        a=json.loads((OUT/f'{name}-analysis.json').read_text())
        n=a['shape'][0]
        for frame in np.unique(np.linspace(0,n-1,5).astype(int)):
            render(name,int(frame))
        render(name,n//2,'saved',{})
        narrower=copy.deepcopy(COMMON)
        narrower['receive'].update(band_f0_mhz=3,band_bw_mhz=2)
        narrower['display'].update(dyn_db=80,gain_db=30)
        render(name,n//2,'review',narrower)
