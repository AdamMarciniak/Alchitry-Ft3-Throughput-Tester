"""Replay real RF only; no hardware access. Save every trial and its provenance."""
from study import *

trials = [
    ('band-1p5-6p5', {'receive': {'band_f0_mhz':4,'band_bw_mhz':5}}),
    ('band-2-6', {'receive': {'band_f0_mhz':4,'band_bw_mhz':4}}),
    ('band-2p5-5', {'receive': {'band_f0_mhz':3.75,'band_bw_mhz':2.5}}),
    ('band-2-4', {'receive': {'band_f0_mhz':3,'band_bw_mhz':2}}),
    ('band-3-5', {'receive': {'band_f0_mhz':4,'band_bw_mhz':2}}),
    ('band-3-6', {'receive': {'band_f0_mhz':4.5,'band_bw_mhz':3}}),
    ('apod-0p5', {'beamformer': {'apod':.5}}),
    ('apod-0p75', {'beamformer': {'apod':.75}}),
    ('avg-2', {'receive': {'avg_sweeps':2}}),
    ('avg-4', {'receive': {'avg_sweeps':4}}),
    ('avg-8', {'receive': {'avg_sweeps':8}}),
    ('comp', {'receive': {'frequency_compounding':True}}),
    ('matched', {'receive': {'matched_filter':True}}),
]

if __name__ == '__main__':
    for name, patch in trials:
        render('saved-rf-'+name, patch)
    for frame in [4,12,28]:
        for cf in [0,.1,.2,.35,2]:
            render(f'held-f{frame}-cf{cf}', {'beamformer':{'cf':cf}}, frame=frame)
