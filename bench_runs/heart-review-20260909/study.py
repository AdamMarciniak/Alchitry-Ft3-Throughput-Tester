"""Offline analysis of user-provided cardiac RF; never controls acquisition."""
import copy,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'host'))
from bench_client import request
from rf_debug import atomic_json,load_session
SOURCE=ROOT/'host/heart-recording.rf.npz.rf.npz'
CONTROL=ROOT/'bench_runs/heart-offline'
BOX=[-65,65,0,165]

def render(name,patch=None,frame=480,box=BOX):
    r=request(CONTROL,{'op':'render','session':str(SOURCE),'frame':frame,
                       'settings':patch or {},'box_mm':box,'search_mm':[-25,25,35,140],
                       'output':str(OUT/name)},timeout=60)
    atomic_json(OUT/name/'trial.json',{'source_session':str(SOURCE),'frame':frame,'box_mm':box,'patch':patch or {}})
    print(name,'rendered',flush=True)
    return r

def axes(shape,box=BOX):
    h,w=shape
    return np.meshgrid(box[0]+(np.arange(w)+.5)*(box[1]-box[0])/w,
                       box[2]+(np.arange(h)+.5)*(box[3]-box[2])/h)

if __name__=='__main__':
    for frame in [0,240,480,720,955]:render(f'original-f{frame}',frame=frame)
