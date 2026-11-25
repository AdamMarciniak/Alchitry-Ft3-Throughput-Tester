from study import *
from metrics import measure
if __name__=='__main__':
    for source in ['validation-1800-a','validation-1600','validation-1800-b']:
        for frame in [8,40,80,112]:
            for mode,p in [('reference',{'beamformer':{'cf':0},'receive':{'avg_sweeps':1}}),
                           ('gentle',{'beamformer':{'cf':.05},'receive':{'avg_sweeps':2}})]:
                p['display']={'dyn_db':95,'gain_db':15}
                name=f'{source}-f{frame}-{mode}'
                render(name,OUT/source/'capture.rf.npz',p,frame=frame)
                measure(name)
    for mode,p in [('wire',{'beamformer':{'cf':2,'apod':1},'receive':{'avg_sweeps':4},'display':{'dyn_db':45,'gain_db':40}}),
                   ('old-gentle',{'beamformer':{'cf':.1},'receive':{'avg_sweeps':2}}),
                   ('compounded',{'receive':{'frequency_compounding':True,'avg_sweeps':1},'display':{'dyn_db':95,'gain_db':15}})]:
        name='final-'+mode
        render(name,OUT/'validation-1800-b/capture.rf.npz',p,frame=80)
        measure(name)
