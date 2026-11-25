from study import *
from metrics import measure
if __name__=='__main__':
    session=OUT/'gain-1800/capture.rf.npz'
    for dyn,gain in [(70,40),(80,30),(90,20),(95,15),(100,10)]:
        name=f'display-{dyn}-{gain}'
        render(name,session,{'beamformer':{'cf':.05},'receive':{'avg_sweeps':2},'display':{'dyn_db':dyn,'gain_db':gain}})
        measure(name)
