from study import *
from metrics import measure
if __name__=='__main__':
    for source in ['baseline-1600','gain-1200','gain-1400','gain-1800','gain-1600']:
        for avg in [1,2,8,16]:
            name=f'{source}-avg{avg}'
            render(name,OUT/source/'capture.rf.npz',{'receive':{'avg_sweeps':avg}},frame=32)
            measure(name)
