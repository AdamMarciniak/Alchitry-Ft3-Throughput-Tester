from study import *

if __name__ == '__main__':
    for label in ['validation-flat-a','validation-flat-b']:
        session=ROOT/'bench_runs/wire-21c-1mm'/label/'capture.rf.npz'
        for frame in [4,12,20,28]:
            for name,patch in [
                ('reference',{'beamformer':{'cf':0,'apod':.75},'receive':{'avg_sweeps':1}}),
                ('gentle',{'beamformer':{'cf':.1,'apod':.75},'receive':{'avg_sweeps':2}}),
                ('wire',{'beamformer':{'cf':2,'apod':1},'receive':{'avg_sweeps':4}})]:
                patch['display']={'dyn_db':70}
                render(f'validation-{label}-f{frame}-{name}',patch,frame=frame,session=session)
    for dyn in [60,65,70,75,80]:
        render(f'display-dyn{dyn}',{'beamformer':{'cf':.1,'apod':.75},
                                  'receive':{'avg_sweeps':2},'display':{'dyn_db':dyn}})
