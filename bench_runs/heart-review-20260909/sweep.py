from study import *
if __name__=='__main__':
    trials=[('display-75-35',{'display':{'dyn_db':75,'gain_db':35}}),
            ('display-65-40',{'display':{'dyn_db':65,'gain_db':40}}),
            ('band-1-3',{'receive':{'band_f0_mhz':2,'band_bw_mhz':2}}),
            ('band-1p5-3p5',{'receive':{'band_f0_mhz':2.5,'band_bw_mhz':2}}),
            ('band-2-4',{'receive':{'band_f0_mhz':3,'band_bw_mhz':2}}),
            ('band-3-5',{'receive':{'band_f0_mhz':4,'band_bw_mhz':2}}),
            ('band-1p5-6p5',{'receive':{'band_f0_mhz':4,'band_bw_mhz':5}}),
            ('water-mask',{'beamformer':{'dead':[2,3,6,7,18,19,22,23,25,46]}}),
            ('cfmap',{'display':{'debug_view':2}}),
            ('cf0p05',{'beamformer':{'cf':.05}}),
            ('compounded',{'receive':{'frequency_compounding':True}}),
            ('matched',{'receive':{'matched_filter':True}}),
            ('average-2',{'receive':{'avg_sweeps':2}}),
            ('apod-0p5',{'beamformer':{'apod':.5}})]
    for name,patch in trials:render(name,patch)
