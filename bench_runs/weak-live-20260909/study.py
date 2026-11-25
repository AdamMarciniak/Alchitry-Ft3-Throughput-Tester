"""Current physical water-bath weak-echo study. No synthetic acquisition fallback."""
import copy, json, sys
from pathlib import Path
import numpy as np
from scipy.ndimage import maximum_filter
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'host'))
from bench_client import request
from rf_debug import atomic_json, load_session
HW=ROOT/'bench_runs/control'
OFF=ROOT/'bench_runs/weak-live-offline'
PRESET=json.loads((ROOT/'host/presets/weak-echo-water.json').read_text())
BASE={'receive':{'bandpass_on':True,'band_f0_mhz':3.5,'band_bw_mhz':3,'avg_sweeps':1,'frequency_compounding':False,'matched_filter':False,'bg_subtract':False,'dejitter_on':False},
      'beamformer':{'apod':.75,'cf':0,'c_m_s':1485,'t0_ns':0,'dead':[2,3,6,7,18,19,22,23,25,46]},
      'display':{'debug_view':0,'auto_gain':False,'gain_db':40,'dyn_db':70,'curve':1}}
BOX=[-35,35,15,115]

def capture(name,tgc=1600,frames=64,extra=None):
    p=copy.deepcopy(PRESET)
    p['acquisition'].update(tgc_min=tgc,tgc_max=tgc)
    for k,v in (extra or {}).items():p.setdefault(k,{}).update(v)
    settings=request(HW,{'op':'configure','settings':p})
    atomic_json(OUT/(name+'-requested.json'),settings)
    result=request(HW,{'op':'capture','frames':frames,'timeout_s':15,
                      'output':str(OUT/name),
                      'note':f'Fresh weak-echo water-bath study, {name}; user confirmed programming USB restored. Prior reported about 21 C, 1 mm wire near 5 cm, container bottom near 10 cm; temperature not newly measured. Fixed existing transmit waveform/HV, flat trims; unidentified possible bubbles. TGC requested {tgc}.'},timeout=45)
    print(name,json.dumps(result),flush=True)
    if not result['accepted']:raise RuntimeError('Capture failed integrity criteria')
    return Path(result['session'])

def axes(shape,box):
    h,w=shape
    return np.meshgrid(box[0]+(np.arange(w)+.5)*(box[1]-box[0])/w,
                       box[2]+(np.arange(h)+.5)*(box[3]-box[2])/h)

def render(name,session,patch=None,frame=32,box=BOX):
    p=copy.deepcopy(BASE)
    for k,v in (patch or {}).items():p.setdefault(k,{}).update(v)
    r=request(OFF,{'op':'render','session':str(session),'frame':frame,'settings':p,
                   'box_mm':box,'search_mm':[-20,20,35,65],
                   'output':str(OUT/name)},timeout=60)
    atomic_json(OUT/name/'trial.json',{'session':str(session),'settings_patch':p,'box_mm':box,'frame':frame})
    print(name,'rendered',flush=True)
    return r

if __name__=='__main__':
    capture('baseline-1600')
