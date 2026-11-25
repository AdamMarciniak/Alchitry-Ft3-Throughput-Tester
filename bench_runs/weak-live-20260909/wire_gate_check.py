"""Analytical RF time gating; derived data, not new physical captures or a display preset."""
from study import *
from metrics import measure
from rf_debug import save_session

if __name__=='__main__':
    source=OUT/'gain-1800/capture.rf.npz'
    s=load_session(source)
    try:
        meta=copy.deepcopy(s.metadata)
        frame=s.rf[32].copy(); samples=frame.shape[1]
        acq=meta['acquired_settings']['acquisition'];fs=acq['fs_hz']
        angle=(np.arange(48)-23.5)*.3375/67.52
        ex=67.52*np.sin(angle);ez=67.52*(np.cos(angle)-1)
        distance=np.hypot(ex+3.212890625,ez-40.390625)/1000
        time_us=(np.arange(samples)/fs+acq['dly_us']*1e-6)[None,:]*1e6
        diff=np.abs(time_us-2*distance[:,None]/1485*1e6)
        for width in [1,2]:
            weight=np.clip((width+.5-diff)/.5,0,1)
            for keep in [True,False]:
                mode='wire-window' if keep else 'wire-excluded'
                rf=np.rint(frame*(weight if keep else 1-weight)).astype(np.int16)
                name=f'DERIVED-{mode}-{width}us'
                m=copy.deepcopy(meta)
                for k in ['acquired_settings','review_settings']:
                    m[k]['source']='derived physical RF; time gated'
                m['derived_rf']={'parent_session':str(source),'parent_frame':32,
                                 'parent_rf_sha256':s.metadata['rf_sha256'],
                                 'description':f'{mode}: predicted wire echo window +/-{width} us plus 0.5 us taper around monostatic arrival; analytic diagnostic only, not a new acquisition.',
                                 'wire_position_mm':[-3.212890625,40.390625]}
                m['initial_review_index']=0
                path=OUT/(name+'.rf.npz')
                save_session(path,[rf],[0.],m,[s.quality[32]],s.tx_reference)
                render(name,path,frame=0)
                measure(name)
    finally:s.close()
