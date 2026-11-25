"""Weak-echo comparisons. Captures are physical; replay labels retain their source."""
import copy
import json
from pathlib import Path
import sys
import numpy as np
from scipy.ndimage import maximum_filter

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'host'))
from bench_client import request
from rf_debug import atomic_json
CONTROL=ROOT/'bench_runs/weak-offline'
BOX=[-30,30,15,80]
OLD=ROOT/'bench_runs/wire-21c-1mm/validation-flat-b/capture.rf.npz'
BASE={'receive':{'bandpass_on':True,'band_f0_mhz':3.5,'band_bw_mhz':3,'avg_sweeps':1,'frequency_compounding':False,'matched_filter':False,'bg_subtract':False,'dejitter_on':False},
      'beamformer':{'apod':1,'cf':0,'c_m_s':1485,'t0_ns':0,'dead':[2,3,6,7,18,19,22,23,25,46]},
      'display':{'debug_view':0,'auto_gain':False,'gain_db':40,'dyn_db':80,'curve':1}}

def axes(shape,box=BOX):
    h,w=shape
    return np.meshgrid(box[0]+(np.arange(w)+.5)*(box[1]-box[0])/w,
                       box[2]+(np.arange(h)+.5)*(box[3]-box[2])/h)

def render(name,patch=None,frame=20,session=OLD,box=BOX):
    p=copy.deepcopy(BASE)
    for k,v in (patch or {}).items():p.setdefault(k,{}).update(v)
    saved=OUT/name/'weak-metrics.json'
    if saved.exists():
        old=json.loads(saved.read_text())
        if old['settings'] != p or old['frame'] != frame or old['source_session'] != str(session):
            raise ValueError('Existing trial has a different definition: '+name)
        return old
    r=request(CONTROL,{'op':'render','session':str(session),'frame':frame,'settings':p,
                      'box_mm':box,'search_mm':[-10,4,47,55],
                      'output':str(OUT/name)},timeout=60)
    mag=np.load(OUT/name/'magnitude.npy')
    xx,zz=axes(mag.shape,box)
    rois={'wire':(-4.5,51.2,2,1),'weak1':(13.6,53.3,2,1.5),'weak2':(2,59.6,2,1.5)}
    details={}
    for label,(x,z,wx,wz) in rois.items():
        gate=(abs(xx-x)<wx)&(abs(zz-z)<wz)
        i=np.unravel_index(np.argmax(np.where(gate,mag,-1)),mag.shape)
        px,pz=float(xx[i]),float(zz[i])
        radius=np.hypot(xx-px,zz-pz)
        bg=(radius>1.8)&(radius<4.5)
        peak=float(mag[i]);noise=float(np.sqrt(np.mean(mag[bg]**2)))
        details[label]={'peak':peak,'position_mm':[px,pz],'local_background_rms':noise,
                        'peak_to_local_background_db':float(20*np.log10(max(peak,1e-12)/max(noise,1e-12)))}
    details['source_session']=str(session)
    details['settings']=p
    details['frame']=frame
    atomic_json(OUT/name/'weak-metrics.json',details)
    print(name,json.dumps({k:{'peak':round(v['peak'],3),'local_db':round(v['peak_to_local_background_db'],2)} for k,v in details.items() if k in rois}),flush=True)
    return details

if __name__=='__main__':
    for cf in [0,.1,.2,.35,.5,1,2]:
        render('saved-rf-cf'+str(cf),{'beamformer':{'cf':cf}})
