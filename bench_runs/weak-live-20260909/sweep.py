from study import *
from metrics import measure
if __name__=='__main__':
    session=OUT/'gain-1800/capture.rf.npz'
    trials=[
        ('band-1p5-6p5',{'receive':{'band_f0_mhz':4,'band_bw_mhz':5}}),
        ('band-2-6',{'receive':{'band_f0_mhz':4,'band_bw_mhz':4}}),
        ('band-2-4',{'receive':{'band_f0_mhz':3,'band_bw_mhz':2}}),
        ('band-2p5-4p5',{'receive':{'band_f0_mhz':3.5,'band_bw_mhz':2}}),
        ('band-3-5',{'receive':{'band_f0_mhz':4,'band_bw_mhz':2}}),
        ('band-3-6',{'receive':{'band_f0_mhz':4.5,'band_bw_mhz':3}}),
        ('matched',{'receive':{'matched_filter':True}}),
        ('comp',{'receive':{'frequency_compounding':True}}),
        ('accept-20',{'beamformer':{'accept_deg':20}}),
        ('accept-25',{'beamformer':{'accept_deg':25}}),
        ('apod-0p5',{'beamformer':{'apod':.5}}),
        ('apod-1',{'beamformer':{'apod':1}}),
    ]+[(f'cf{cf}',{'beamformer':{'cf':cf}}) for cf in [.05,.1,.2,.35,.5,1,2]]
    for name,patch in trials:
        render('sweep-'+name,session,patch,frame=32)
        measure('sweep-'+name)
