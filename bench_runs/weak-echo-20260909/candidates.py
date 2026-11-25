from study import *

if __name__ == '__main__':
    for apod in [.5,.75,1]:
        for cf in [0,.1,.2]:
            render(f'candidate-a{apod}-cf{cf}',
                   {'beamformer':{'apod':apod,'cf':cf},
                    'receive':{'avg_sweeps':2},
                    'display':{'dyn_db':70}})
    for frame in [4,12,28]:
        for apod in [.75,1]:
            render(f'candidate-held-f{frame}-a{apod}',
                   {'beamformer':{'apod':apod,'cf':.1},
                    'receive':{'avg_sweeps':2},
                    'display':{'dyn_db':70}},frame=frame)
