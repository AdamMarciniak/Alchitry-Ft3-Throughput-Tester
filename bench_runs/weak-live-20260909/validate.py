from study import *
if __name__=='__main__':
    extra={'beamformer':{'cf':.05},'display':{'dyn_db':95,'gain_db':15}}
    for name,gain in [('validation-1800-a',1800),('validation-1600',1600),('validation-1800-b',1800)]:
        p=capture(name,tgc=gain,frames=128,extra=extra)
        d=json.loads((p.parent/'capture.report.json').read_text())
        peaks=[e['peak_counts'] for e in d['elements']]
        clipped=[e['element'] for e in d['elements'] if e['clipped_fraction']]
        print(name,'max ADC',max(peaks),'clipped channels',clipped,flush=True)
        if clipped:raise RuntimeError('Validation capture clipped')
